-- hapax-df-lifecycle.lua — Full lifecycle automation for hapax fortress governor
--
-- Handles: Title → World Gen → Site Selection → Embark → Bridge Start
-- Detects current screen state and resumes from any point.
--
-- Usage:
--   hapax-df-lifecycle start    -- begin lifecycle automation
--   hapax-df-lifecycle stop     -- cancel all lifecycle timers
--   hapax-df-lifecycle status   -- show current state
--
-- Auto-start: Add "hapax-df-lifecycle start" to dfhack.init

local gui = require("gui")

local GLOBAL_KEY = "hapax-df-lifecycle"
local POLL_FRAMES = 10
local WORLDGEN_TIMEOUT_S = 300  -- 5 min max for world gen

local state = {
    phase = "idle",
    started = false,
    fortress_ready = false,
    worldgen_started = false,
    title_attempts = 0,
    error = nil,
}

-- -----------------------------------------------------------------------
-- Screen detection
-- -----------------------------------------------------------------------

local function is_title()
    return dfhack.gui.getViewscreenByType(df.viewscreen_titlest, 0) ~= nil
end

local function is_worldgen()
    return dfhack.gui.getViewscreenByType(df.viewscreen_new_regionst, 0) ~= nil
end

local function is_site_select()
    return dfhack.gui.getViewscreenByType(df.viewscreen_choose_start_sitest, 0) ~= nil
end

local function is_embark_prep()
    return dfhack.gui.getViewscreenByType(df.viewscreen_setupdwarfgamest, 0) ~= nil
end

local function is_fortress()
    return dfhack.world.isFortressMode()
end

local function is_loading()
    return dfhack.gui.getViewscreenByType(df.viewscreen_initial_prepst, 0) ~= nil
end

local function current_screen()
    if is_fortress() then return "fortress" end
    if is_embark_prep() then return "embark_prep" end
    if is_site_select() then return "site_select" end
    if is_worldgen() then return "worldgen" end
    if is_title() then return "title" end
    if is_loading() then return "loading" end
    return "unknown"
end

local function press(key)
    local scr = dfhack.gui.getCurViewscreen()
    if scr then gui.simulateInput(scr, key) end
end

-- -----------------------------------------------------------------------
-- Phase handlers
-- -----------------------------------------------------------------------

local function handle_title()
    local title = dfhack.gui.getViewscreenByType(df.viewscreen_titlest, 0)
    if not title then return end

    -- Find menu item indices by type
    local continue_idx, newworld_idx, start_idx = nil, nil, nil
    for idx = 0, #title.menu_line_id - 1 do
        local item = title.menu_line_id[idx]
        if item == 0 then continue_idx = idx end     -- Continue (resume fortress)
        if item == 1 then start_idx = idx end         -- Start Playing (pick world)
        if item == 2 then newworld_idx = idx end      -- New World
    end

    -- Prefer Continue (resume existing fortress)
    if continue_idx then
        dfhack.println("[hapax-lifecycle] Found existing fortress, resuming...")
        title.selected = continue_idx
        -- Bypass overlay interception: set game_start_proceed directly
        title.game_start_proceed = 1
        state.phase = "waiting_fortress"
        return
    end

    -- Try Start Playing (if worlds exist but no active fortress)
    if start_idx then
        dfhack.println("[hapax-lifecycle] Found saved worlds, starting...")
        title.selected = start_idx
        title.game_start_proceed = 1
        state.phase = "site_select"
        return
    end

    -- No saves at all — create new world
    if newworld_idx then
        state.title_attempts = (state.title_attempts or 0) + 1
        if state.title_attempts > 3 then
            dfhack.println("[hapax-lifecycle] Title navigation failed after 3 attempts, stopping")
            state.error = "title_navigation_failed"
            state.started = false
            return
        end
        dfhack.println(("[hapax-lifecycle] Creating new world (attempt %d)..."):format(state.title_attempts))
        title.selected = newworld_idx
        -- Try both mechanisms
        title.game_start_proceed = 1
        -- Also try simulateInput as fallback
        gui.simulateInput(title, "SELECT")
        state.phase = "worldgen"
        return
    end

    dfhack.printerr("[hapax-lifecycle] Cannot find menu options on title screen")
    state.error = "title_menu_missing"
end

local function handle_worldgen()
    if not is_worldgen() then return end

    -- Check focus string to determine sub-state
    local focus = dfhack.gui.getCurFocus()
    local focus_str = focus and focus[1] or ""

    if focus_str:find("Loading") or focus_str:find("Generating") then
        -- World gen in progress, just wait
        return
    end

    -- On parameter screen — accept defaults and generate
    if not state.worldgen_started then
        dfhack.println("[hapax-lifecycle] Starting world generation with defaults...")
        state.worldgen_started = true
        -- Try both SELECT and the proceed mechanism
        local scr = dfhack.gui.getCurViewscreen()
        gui.simulateInput(scr, "SELECT")
    end
    -- World gen takes minutes. Phase stays worldgen until a different screen appears.
end

local function handle_site_select()
    if not is_site_select() then return end

    dfhack.println("[hapax-lifecycle] On site selection — embarking at default site...")
    -- 'e' key = embark in site selection
    press(df.interface_key.SETUP_EMBARK)
    state.phase = "embark_prep"
end

local function handle_embark_prep()
    if not is_embark_prep() then return end

    local focus = dfhack.gui.getCurFocus()
    local focus_str = focus and focus[1] or ""

    -- If on confirmation dialog, confirm
    if focus_str:find("Confirm") then
        dfhack.println("[hapax-lifecycle] Confirming embark...")
        press("SELECT")
        state.phase = "waiting_fortress"
        return
    end

    -- Hit embark / Play Now
    dfhack.println("[hapax-lifecycle] Embarking with defaults...")
    press(df.interface_key.SETUP_EMBARK)
end

-- -----------------------------------------------------------------------
-- Bridge startup
-- -----------------------------------------------------------------------

local function dismiss_dialogs()
    -- Dismiss any modal dialogs (embark welcome, tutorial, etc.)
    local gui_mod = require("gui")
    local function try_dismiss(text)
        local results = {}
        local w, h = dfhack.screen.getWindowSize()
        for y = 0, h - 1 do
            local row = {}
            for x = 0, w - 1 do
                local pen = dfhack.screen.readTile(x, y)
                if pen then
                    local ch = pen.ch
                    if type(ch) == "number" and ch >= 32 and ch < 127 then
                        row[#row + 1] = string.char(ch)
                    elseif #row > 0 and row[#row] ~= " " then
                        row[#row + 1] = " "
                    end
                else
                    row[#row + 1] = " "
                end
            end
            local line = table.concat(row)
            local s = line:find(text, 1, true)
            if s then
                local click_x = s - 1 + math.floor(#text / 2)
                df.global.gps.mouse_x = click_x
                df.global.gps.mouse_y = y
                df.global.enabler.tracking_on = 1
                gui_mod.simulateInput(dfhack.gui.getCurViewscreen(), "_MOUSE_L")
                dfhack.println(("[hapax-lifecycle] Dismissed '%s' at (%d, %d)"):format(text, click_x, y))
                return true
            end
        end
        return false
    end

    -- Try dismissing common dialogs
    try_dismiss("Okay")
    dfhack.timeout(5, "frames", function()
        try_dismiss("Okay")  -- second attempt for nested dialogs
    end)
end

local function start_bridge()
    if state.fortress_ready then return end
    state.fortress_ready = true
    state.phase = "active"

    -- Dismiss any modal dialogs before starting bridge
    dismiss_dialogs()

    dfhack.println("[hapax-lifecycle] Fortress mode active! Starting bridge in 30 frames...")
    dfhack.timeout(30, "frames", function()
        local ok, err = dfhack.pcall(function()
            dfhack.run_script("hapax-df-bridge", "start")
        end)
        if ok then
            dfhack.println("[hapax-lifecycle] Bridge started successfully")
                    -- Unpause the game
                    dfhack.timeout(10, "frames", function()
                        df.global.pause_state = false
                        dfhack.println("[hapax-lifecycle] Game unpaused")
                    end)
        else
            dfhack.printerr("[hapax-lifecycle] Bridge failed: " .. tostring(err))
            state.error = tostring(err)
        end
    end)
end

-- -----------------------------------------------------------------------
-- Main tick
-- -----------------------------------------------------------------------

local function lifecycle_tick()
    if not state.started then return end

    local screen = current_screen()

    if screen == "fortress" then
        start_bridge()
        return
    end

    if screen == "loading" or screen == "unknown" then
        return  -- wait for screen to settle
    end

    if screen == "title" and state.phase ~= "worldgen" then
        handle_title()
    elseif screen == "worldgen" then
        handle_worldgen()
    elseif screen == "site_select" then
        handle_site_select()
    elseif screen == "embark_prep" then
        handle_embark_prep()
    end
end

-- -----------------------------------------------------------------------
-- State change hook (backup detection)
-- -----------------------------------------------------------------------

dfhack.onStateChange[GLOBAL_KEY] = function(code)
    if not state.started then return end

    if code == SC_MAP_LOADED and dfhack.world.isFortressMode() then
        dfhack.println("[hapax-lifecycle] SC_MAP_LOADED — fortress confirmed")
        start_bridge()
    end

    if code == SC_MAP_UNLOADED then
        state.fortress_ready = false
        state.phase = "idle"
    end
end

-- -----------------------------------------------------------------------
-- CLI
-- -----------------------------------------------------------------------

local function start()
    state.started = true
    state.fortress_ready = false
    state.worldgen_started = false
    state.title_attempts = 0
    state.error = nil

    local screen = current_screen()
    dfhack.println(("[hapax-lifecycle] Starting (screen: %s)"):format(screen))

    if screen == "fortress" then
        start_bridge()
        return
    end

    -- Delay polling start to let DF finish title screen initialization
    dfhack.println("[hapax-lifecycle] Waiting 3s for title screen to stabilize...")
    dfhack.timeout(180, "frames", function()
        dfhack.println("[hapax-lifecycle] Starting navigation polling")
        local repeatUtil = require("repeat-util")
        repeatUtil.scheduleEvery(GLOBAL_KEY, POLL_FRAMES, "frames", lifecycle_tick)
    end)
end

local function stop()
    state.started = false
    local repeatUtil = require("repeat-util")
    repeatUtil.cancel(GLOBAL_KEY)
    dfhack.onStateChange[GLOBAL_KEY] = nil
    dfhack.pcall(function() dfhack.run_script("hapax-df-bridge", "stop") end)
    dfhack.println("[hapax-lifecycle] Stopped")
end

local function show_status()
    dfhack.println(("[hapax-lifecycle] Phase: %s | Screen: %s | Ready: %s"):format(
        state.phase, current_screen(), tostring(state.fortress_ready)))
    if state.error then
        dfhack.println(("[hapax-lifecycle] Error: %s"):format(state.error))
    end
end

local args = {...}
if #args == 0 or args[1] == "start" then
    start()
elseif args[1] == "stop" then
    stop()
elseif args[1] == "status" then
    show_status()
else
    dfhack.printerr("Usage: hapax-df-lifecycle [start|stop|status]")
end
