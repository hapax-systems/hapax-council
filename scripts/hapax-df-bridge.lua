-- hapax-df-bridge.lua -- DFHack bridge for hapax fortress governance
--
-- Usage:
--   hapax-df-bridge start   -- begin state export and command polling
--   hapax-df-bridge stop    -- stop all timers
--   hapax-df-bridge status  -- check if running
--
-- See docs/superpowers/specs/2026-03-23-dfhack-bridge-protocol.md

local json = require("json")
local gui = require("gui")
local repeatUtil = require("repeat-util")
local eventful = require("plugins.eventful")

local STATE_DIR = "/dev/shm/hapax-df"
local STATE_FILE = STATE_DIR .. "/state.json"
local COMMANDS_FILE = STATE_DIR .. "/commands.json"
local RESULTS_FILE = STATE_DIR .. "/results.json"

-- All intervals in frames (at ~100 FPS): 1s = ~100 frames
local FAST_INTERVAL = 300   -- frames (~3 seconds)
local FULL_INTERVAL = 600   -- frames (~6 seconds)
local CMD_INTERVAL = 30     -- frames (~0.3 seconds)

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
    local total = 0
    -- FOOD = prepared meals
    local ok_food, food = pcall(function() return df.global.world.items.other.FOOD end)
    if ok_food and food then total = total + #food end
    -- PLANT = raw plants (edible but not yet cooked)
    local ok_plant, plant = pcall(function() return df.global.world.items.other.PLANT end)
    if ok_plant and plant then total = total + #plant end
    if total > 0 then return total end
    -- Last resort: ANY_COOKABLE (may not exist in all builds)
    local ok_any, items = pcall(function() return df.global.world.items.other.ANY_COOKABLE end)
    if ok_any and items then return #items end
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

-- Auto-dismiss blocking dialogs (Okay buttons, announcements)
local function dismiss_dialogs()
    local w, h = dfhack.screen.getWindowSize()
    for y = 0, h - 1 do
        local row = {}
        for x = 0, w - 1 do
            local pen = dfhack.screen.readTile(x, y)
            if pen then
                local ch = pen.ch
                if type(ch) == "number" and ch >= 32 and ch < 127 then
                    row[#row + 1] = string.char(ch)
                else
                    row[#row + 1] = " "
                end
            else
                row[#row + 1] = " "
            end
        end
        local line = table.concat(row)
        local s = line:find("Okay", 1, true)
        if s then
            local click_x = s - 1 + 2
            df.global.gps.mouse_x = click_x
            df.global.gps.mouse_y = y
            df.global.enabler.tracking_on = 1
            local scr = dfhack.gui.getCurViewscreen()
            gui.simulateInput(scr, "_MOUSE_L")
            return true
        end
    end
    -- Handle ESC-dismissable screens (nobles, announcements, petitions, diplomacy)
    local focus = dfhack.gui.getCurFocus()
    local focus_str = focus and focus[1] or ""
    if focus_str:find("nobles") or focus_str:find("announcement")
       or focus_str:find("petitions") or focus_str:find("diplomacy") then
        gui.simulateInput(dfhack.gui.getCurViewscreen(), "LEAVESCREEN")
        return true
    end
    return false
end

-- Export state to /dev/shm (always full)
local function export_fast()
    -- Dismiss any blocking dialogs before export
    dismiss_dialogs()
    tick_counter = tick_counter + 1
    local state = build_full_state()
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

-- Find embark center
local function find_embark_center()
    -- Method 1: Wagon
    local wagons_ok, wagons = pcall(function() return df.global.world.buildings.other.WAGON end)
    if wagons_ok and wagons then
        for _, wagon in ipairs(wagons) do
            if wagon.age == 0 then
                return wagon.centerx, wagon.centery, wagon.z
            end
        end
    end
    -- Method 2: First citizen position
    local citizens = get_citizens()
    if #citizens > 0 then
        local pos = dfhack.units.getPosition(citizens[1])
        if pos then return pos.x, pos.y, pos.z end
    end
    return nil, nil, nil
end

-- Find diggable layer below surface
local function find_dig_layer(cx, cy, surface_z)
    for z = surface_z - 1, surface_z - 20, -1 do
        local tt = dfhack.maps.getTileType(cx, cy, z)
        if tt then
            local attrs = df.tiletype.attrs[tt]
            if attrs.shape == df.tiletype_shape.WALL
               and not dfhack.maps.isTileAquifer(xyz2pos(cx, cy, z)) then
                return z
            end
        end
    end
    return nil  -- no suitable dig layer found; callers must handle nil
end

-- Designate rectangular area for digging
local function designate_rect(x1, y1, z, x2, y2, dig_type)
    dig_type = dig_type or df.tile_dig_designation.Default
    local count = 0
    for x = math.min(x1,x2), math.max(x1,x2) do
        for y = math.min(y1,y2), math.max(y1,y2) do
            local flags = dfhack.maps.getTileFlags(x, y, z)
            if flags then
                local tt = dfhack.maps.getTileType(x, y, z)
                if tt then
                    local attrs = df.tiletype.attrs[tt]
                    if attrs.shape == df.tiletype_shape.WALL then
                        flags.dig = dig_type
                        dfhack.maps.getTileBlock(x, y, z).flags.designated = true
                        count = count + 1
                    end
                end
            end
        end
    end
    dfhack.job.checkDesignationsNow()
    return count
end

-- Poll for commands
local function poll_commands()
    local f = io.open(COMMANDS_FILE, "r")
    if not f then return end

    local raw = f:read("*a")
    f:close()
    -- Truncate instead of remove (os.remove not available in DFHack sandbox)
    local truncate = io.open(COMMANDS_FILE, "w")
    if truncate then truncate:close() end

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
            elseif action == "dig_room" then
                -- Dig a rectangular room with stairs
                local cx, cy, cz = cmd.x, cmd.y, cmd.z
                local w, h = cmd.width or 11, cmd.height or 11
                -- Auto-detect center if sentinel (0,0,0)
                if cx == 0 and cy == 0 and cz == 0 then
                    local ecx, ecy, ecz = find_embark_center()
                    if not ecx then
                        dfhack.printerr("hapax-df-bridge: dig_room failed — cannot find embark center")
                        return
                    end
                    local dig_z = find_dig_layer(ecx, ecy, ecz)
                    if not dig_z then
                        dfhack.printerr("hapax-df-bridge: dig_room failed — no suitable dig layer found")
                        return
                    end
                    cx = ecx - math.floor(w/2)
                    cy = ecy - math.floor(h/2)
                    cz = dig_z
                    -- Dig stairs at embark center
                    local stair_flags = dfhack.maps.getTileFlags(ecx, ecy, ecz)
                    if stair_flags then
                        stair_flags.dig = df.tile_dig_designation.DownStair
                        dfhack.maps.getTileBlock(ecx, ecy, ecz).flags.designated = true
                    end
                    local stair_flags2 = dfhack.maps.getTileFlags(ecx, ecy, cz)
                    if stair_flags2 then
                        stair_flags2.dig = df.tile_dig_designation.UpStair
                        dfhack.maps.getTileBlock(ecx, ecy, cz).flags.designated = true
                    end
                end
                -- Bounds check before designating
                local map_x, map_y, map_z = dfhack.maps.getTileSize()
                if cx < 0 or cy < 0 or cz < 0
                   or cx + w > map_x or cy + h > map_y or cz >= map_z then
                    dfhack.printerr(("hapax-df-bridge: dig_room out of bounds (%d,%d,%d) %dx%d"):format(cx, cy, cz, w, h))
                    return
                end
                local count = designate_rect(cx, cy, cz, cx + w - 1, cy + h - 1)
                dfhack.println(("hapax-df-bridge: designated %d tiles for digging at z=%d"):format(count, cz))

            elseif action == "build_workshop" then
                -- Place a workshop
                local ws_type = cmd.workshop_type or "Craftsdwarfs"
                local ws_enum = df.workshop_type[ws_type]
                if not ws_enum then
                    dfhack.printerr("hapax-df-bridge: unknown workshop type: " .. ws_type)
                else
                    local wx, wy, wz = cmd.x, cmd.y, cmd.z
                    -- Auto-detect position if sentinel
                    if wx == 0 and wy == 0 and wz == 0 then
                        local ecx, ecy, ecz = find_embark_center()
                        if not ecx then
                            dfhack.printerr("hapax-df-bridge: build_workshop failed — cannot find embark center")
                            return
                        end
                        local dig_z = find_dig_layer(ecx, ecy, ecz)
                        if not dig_z then
                            dfhack.printerr("hapax-df-bridge: build_workshop failed — no suitable dig layer")
                            return
                        end
                        wz = dig_z
                        -- Apply offset from command params (Python sends relative offsets)
                        wx = ecx + (cmd.offset_x or 0)
                        wy = ecy + (cmd.offset_y or 0)
                    end
                    -- Bounds check before xyz2pos
                    local map_x, map_y, map_z = dfhack.maps.getTileSize()
                    if wx < 0 or wy < 0 or wz < 0
                       or wx + 3 > map_x or wy + 3 > map_y or wz >= map_z then
                        dfhack.printerr(("hapax-df-bridge: workshop out of bounds (%d,%d,%d)"):format(wx, wy, wz))
                        return
                    end
                    local bld, err = dfhack.buildings.constructBuilding{
                        type = df.building_type.Workshop,
                        subtype = ws_enum,
                        pos = xyz2pos(wx, wy, wz),
                        width = 3, height = 3,
                    }
                    if bld then
                        dfhack.println(("hapax-df-bridge: placed %s workshop at (%d,%d,%d)"):format(ws_type, wx, wy, wz))
                    else
                        dfhack.printerr(("hapax-df-bridge: workshop placement failed: %s"):format(tostring(err)))
                    end
                end

            elseif action == "import_orders" then
                local lib = cmd.library or "library/basic"
                dfhack.run_command('orders', 'import', lib)
                dfhack.println(("hapax-df-bridge: imported orders from %s"):format(lib))

            elseif action == "enable_plugin" then
                dfhack.run_command('enable', cmd.plugin or "")

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
    -- All timers on frames so they work while game is paused
    repeatUtil.scheduleEvery("hapax-df-fast", FAST_INTERVAL, "frames", export_fast)
    repeatUtil.scheduleEvery("hapax-df-full", FULL_INTERVAL, "frames", export_full)
    -- Commands must poll on frames (not ticks) so unpause works while game is paused
    repeatUtil.scheduleEvery("hapax-df-cmds", CMD_INTERVAL, "frames", poll_commands)

    -- Register event hooks
    eventful.onInvasion.hapax = on_invasion
    eventful.onUnitDeath.hapax = on_unit_death

    -- Initial full export
    export_full()

    -- Enable labor management
    -- Enable labor management (autolabor available in 53.x, labormanager may not be)
    local labor_ok, labor_err = pcall(function()
        dfhack.run_command("enable", "labormanager")
    end)
    if not labor_ok then
        pcall(function() dfhack.run_command("enable", "autolabor") end)
        dfhack.println("hapax-df-bridge: autolabor enabled (labormanager unavailable)")
    else
        dfhack.println("hapax-df-bridge: labormanager enabled")
    end

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
