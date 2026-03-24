-- hapax-df-bridge.lua -- DFHack bridge for hapax fortress governance
--
-- Usage:
--   hapax-df-bridge start   -- begin state export and command polling
--   hapax-df-bridge stop    -- stop all timers
--   hapax-df-bridge status  -- check if running
--
-- See docs/superpowers/specs/2026-03-23-dfhack-bridge-protocol.md

local json = require("json")
local repeatUtil = require("repeat-util")
local eventful = require("plugins.eventful")

local STATE_DIR = "/dev/shm/hapax-df"
local STATE_FILE = STATE_DIR .. "/state.json"
local COMMANDS_FILE = STATE_DIR .. "/commands.json"
local RESULTS_FILE = STATE_DIR .. "/results.json"

local FAST_INTERVAL = 120   -- ticks (1 in-game day)
local FULL_INTERVAL = 1200  -- ticks (1 season)
local CMD_INTERVAL = 10     -- ticks

local event_buffer = {}
local tick_counter = 0

-- Ensure output directory exists
local function ensure_dir()
    if not dfhack.filesystem.isdir(STATE_DIR) then
        dfhack.filesystem.mkdir_recursive(STATE_DIR)
    end
end

-- Atomic write: write to .tmp, rename to final
local function atomic_write(path, content)
    local tmp = path .. ".tmp"
    local f = io.open(tmp, "w")
    if not f then
        dfhack.printerr("hapax-df-bridge: cannot open " .. tmp)
        return false
    end
    f:write(content)
    f:close()
    os.rename(tmp, path)
    return true
end

-- Count alive citizens
local function get_citizens()
    local citizens = {}
    for _, unit in ipairs(df.global.world.units.active) do
        if dfhack.units.isCitizen(unit) and dfhack.units.isAlive(unit) then
            table.insert(citizens, unit)
        end
    end
    return citizens
end

-- Count items by type — simplified, avoid unavailable API calls
local function count_food()
    local ok, items = pcall(function() return df.global.world.items.other.ANY_COOKABLE end)
    if ok and items then return #items end
    -- Fallback: count food items from FOOD category
    local ok2, food = pcall(function() return df.global.world.items.other.FOOD end)
    if ok2 and food then return #food end
    return 0
end

local function count_drink()
    local ok, items = pcall(function() return df.global.world.items.other.DRINK end)
    if ok and items then return #items end
    return 0
end

-- Count hostile units
local function count_threats()
    local count = 0
    for _, unit in ipairs(df.global.world.units.active) do
        if dfhack.units.isActive(unit) and dfhack.units.isInvader(unit) then
            count = count + 1
        end
    end
    return count
end

-- Count idle dwarves
local function count_idle(citizens)
    local count = 0
    for _, unit in ipairs(citizens) do
        if not unit.job.current_job then
            count = count + 1
        end
    end
    return count
end

-- Get worst stress value among citizens
local function worst_stress(citizens)
    local worst = 0
    for _, unit in ipairs(citizens) do
        if unit.status.current_soul then
            local stress = unit.status.current_soul.personality.stress
            if stress > worst then
                worst = stress
            end
        end
    end
    return worst
end

-- Build fast state (every 120 ticks)
local function build_fast_state()
    local citizens = get_citizens()
    local tick = df.global.cur_year_tick
    local year = df.global.cur_year
    local month = tick // 33600  -- ticks per month
    local season = month // 3
    local day = (tick % 33600) // 1200

    local state = {
        timestamp = os.time(),
        game_tick = df.global.cur_year_tick + df.global.cur_year * 403200,
        year = year,
        season = season,
        month = month,
        day = day,
        fortress_name = dfhack.df2utf(dfhack.Translation(df.global.world.world_data.active_site[0].name)),
        paused = df.global.pause_state,
        population = #citizens,
        food_count = count_food(),
        drink_count = count_drink(),
        active_threats = count_threats(),
        job_queue_length = (pcall(function() return #df.global.world.manager_orders.all end) and #df.global.world.manager_orders.all or 0),
        idle_dwarf_count = count_idle(citizens),
        most_stressed_value = worst_stress(citizens),
        pending_events = event_buffer,
    }

    -- Clear event buffer after inclusion
    event_buffer = {}

    return state
end

-- Build full state (extends fast with unit details, stockpiles, etc.)
local function build_full_state()
    local state = build_fast_state()
    local citizens = get_citizens()

    -- Unit details
    state.units = {}
    for _, unit in ipairs(citizens) do
        local skills = {}
        if unit.status.current_soul then
            for _, skill in ipairs(unit.status.current_soul.skills) do
                table.insert(skills, {
                    name = df.job_skill[skill.id],
                    level = skill.rating,
                })
            end
        end

        local mood = "normal"
        if unit.mood >= 0 then
            mood = df.mood_type[unit.mood] or "unknown"
        end

        table.insert(state.units, {
            id = unit.id,
            name = dfhack.df2utf(dfhack.units.getReadableName(unit)),
            profession = df.profession[unit.profession],
            skills = skills,
            stress = unit.status.current_soul and unit.status.current_soul.personality.stress or 0,
            mood = mood,
            current_job = unit.job.current_job and df.job_type[unit.job.current_job.job_type] or "idle",
            military_squad_id = unit.military.squad_id >= 0 and unit.military.squad_id or json.null,
        })
    end

    -- Military squads
    state.squads = {}
    for _, squad in ipairs(df.global.world.squads.all) do
        local members = {}
        for _, pos in ipairs(squad.positions) do
            if pos.occupant >= 0 then
                table.insert(members, pos.occupant)
            end
        end
        if #members > 0 then
            table.insert(state.squads, {
                id = squad.id,
                name = dfhack.df2utf(squad.alias),
                member_ids = members,
                equipment_quality = 0.5,  -- TODO: compute from equipment
                training_level = 0.5,     -- TODO: compute from skills
            })
        end
    end

    -- Stockpile summary — defensive access for 53.x item categories
    local function safe_count(category)
        local ok, items = pcall(function() return df.global.world.items.other[category] end)
        if ok and items then
            local ok2, n = pcall(function() return #items end)
            if ok2 then return n end
        end
        return 0
    end
    state.stockpiles = {
        food = count_food(),
        drink = count_drink(),
        wood = safe_count("WOOD"),
        stone = safe_count("BOULDER"),
        metal_bars = safe_count("BAR"),
        cloth = safe_count("CLOTH"),
        thread = safe_count("THREAD"),
        weapons = safe_count("WEAPON"),
        armor = safe_count("ARMOR"),
        ammo = safe_count("AMMO"),
        mechanisms = safe_count("TRAPCOMP"),
        seeds = safe_count("SEEDS"),
        gems = safe_count("ROUGH"),
        leather = safe_count("SKIN_TANNED"),
        bones = safe_count("BONES"),
        shells = safe_count("SHELL"),
        crafts = safe_count("CRAFT"),
        furniture = 0,
    }

    -- Wealth — defensive access
    local wealth_ok, wealth = pcall(function()
        local econ = df.global.plotinfo.tasks
        return {
            created = econ.wealth.total or 0,
            exported = econ.wealth.exported or 0,
            imported = econ.wealth.imported or 0,
        }
    end)
    state.wealth = wealth_ok and wealth or {created = 0, exported = 0, imported = 0}

    -- Map summary (basic)
    state.map_summary = {
        z_levels_explored = 0,  -- TODO: count explored z-levels
        cavern_layers_breached = 0,  -- TODO: check cavern flags
        has_magma_access = false,
        has_water_source = true,  -- assume true for now
        aquifer_present = false,
    }

    -- Workshops — defensive
    state.workshops = {}
    pcall(function()
        for _, bld in ipairs(df.global.world.buildings.all) do
            if df.building_workshopst:is_instance(bld) then
                local job_count = pcall(function() return #bld.jobs end) and #bld.jobs or 0
                local job_name = "idle"
                if job_count > 0 then
                    pcall(function() job_name = df.job_type[bld.jobs[0].job_type] or "unknown" end)
                end
                table.insert(state.workshops, {
                    type = tostring(bld.type),
                    x = bld.x1, y = bld.y1, z = bld.z,
                    is_active = job_count > 0,
                    current_job = job_name,
                })
            end
        end
    end)

    -- Buildings summary
    state.buildings = {
        doors = 0, beds = 0, tables = 0, chairs = 0,
        statues = 0, armor_stands = 0, weapon_racks = 0,
        coffins = 0, trade_depot = 0,
    }
    -- TODO: count building types

    state.nobles = {}
    state.strange_moods = {}

    return state
end

-- Export state to /dev/shm
local function export_fast()
    tick_counter = tick_counter + 1
    local state = build_fast_state()
    local ok = atomic_write(STATE_FILE, json.encode(state))
    if not ok then
        dfhack.printerr("hapax-df-bridge: failed to write state")
    end
end

local function export_full()
    local state = build_full_state()
    local ok = atomic_write(STATE_FILE, json.encode(state))
    if ok then
        dfhack.println("hapax-df-bridge: full state exported (tick " .. df.global.cur_year_tick .. ")")
    end
end

-- Poll for commands
local function poll_commands()
    local f = io.open(COMMANDS_FILE, "r")
    if not f then return end

    local raw = f:read("*a")
    f:close()
    os.remove(COMMANDS_FILE)

    local ok, cmds = pcall(json.decode, raw)
    if not ok or type(cmds) ~= "table" then
        dfhack.printerr("hapax-df-bridge: invalid commands JSON")
        return
    end

    local results = {}
    for _, cmd in ipairs(cmds) do
        local cmd_id = cmd.id or "unknown"
        local action = cmd.action or ""
        local success, err = pcall(function()
            if action == "raw" then
                dfhack.run_command(cmd.command or "")
            elseif action == "pause" then
                if cmd.state == false then
                    df.global.pause_state = false
                else
                    df.global.pause_state = true
                end
            elseif action == "save" then
                dfhack.run_command("quicksave")
            elseif action == "dig" or action == "build" or action == "place" then
                -- quickfort apply from string
                dfhack.run_command("quickfort", "run", cmd.blueprint or "")
            elseif action == "order" then
                -- Manager order
                dfhack.run_command("orders", "import", cmd.file or "")
            else
                dfhack.printerr("hapax-df-bridge: unknown action: " .. action)
            end
        end)
        results[cmd_id] = {success = success, error = err and tostring(err) or nil}
    end

    atomic_write(RESULTS_FILE, json.encode(results))
end

-- Event hooks
local function on_invasion(civ_id)
    table.insert(event_buffer, {
        type = "siege",
        attacker_civ = tostring(civ_id),
        force_size = 0,  -- TODO: count invaders
    })
end

local function on_unit_death(unit_id)
    local unit = df.unit.find(unit_id)
    if unit and dfhack.units.isCitizen(unit) then
        table.insert(event_buffer, {
            type = "death",
            unit_id = unit_id,
            unit_name = dfhack.df2utf(dfhack.units.getReadableName(unit)),
            cause = "unknown",  -- TODO: extract death cause
        })
    end
end

-- Start/stop/status
local function start()
    ensure_dir()

    -- Register periodic tasks
    repeatUtil.scheduleEvery("hapax-df-fast", FAST_INTERVAL, "ticks", export_fast)
    repeatUtil.scheduleEvery("hapax-df-full", FULL_INTERVAL, "ticks", export_full)
    -- Commands must poll on frames (not ticks) so unpause works while game is paused
    repeatUtil.scheduleEvery("hapax-df-cmds", CMD_INTERVAL, "frames", poll_commands)

    -- Register event hooks
    eventful.onInvasion.hapax = on_invasion
    eventful.onUnitDeath.hapax = on_unit_death

    -- Initial full export
    export_full()

    dfhack.println("hapax-df-bridge: started")
end

local function stop()
    repeatUtil.cancel("hapax-df-fast")
    repeatUtil.cancel("hapax-df-full")
    repeatUtil.cancel("hapax-df-cmds")

    eventful.onInvasion.hapax = nil
    eventful.onUnitDeath.hapax = nil

    dfhack.println("hapax-df-bridge: stopped")
end

local function status()
    if repeatUtil.isScheduled("hapax-df-fast") then
        dfhack.println("hapax-df-bridge: running (tick_counter=" .. tick_counter .. ")")
    else
        dfhack.println("hapax-df-bridge: stopped")
    end
end

-- CLI dispatch
local args = {...}
if #args == 0 or args[1] == "start" then
    start()
elseif args[1] == "stop" then
    stop()
elseif args[1] == "status" then
    status()
else
    dfhack.printerr("Usage: hapax-df-bridge [start|stop|status]")
end
