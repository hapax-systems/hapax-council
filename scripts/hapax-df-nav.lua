-- hapax-df-nav.lua — Reliable screen reader + navigator for DF 53.x
--
-- Core principle: scan screen buffer for text → click by label → verify transition.
-- Every navigation step is verified. Failures retry with backoff.
--
-- Usage:
--   hapax-df-nav dump                 -- dump entire screen as text
--   hapax-df-nav find <text>          -- find text on screen, report coords
--   hapax-df-nav click <text>         -- find and click a named button
--   hapax-df-nav focus                -- show current focus string
--   hapax-df-nav tree                 -- dump screen text + focus for tree mapping
--   hapax-df-nav navigate <target>    -- navigate to a target screen (title/worldgen/embark/fortress)

local gui = require("gui")

-- -----------------------------------------------------------------------
-- Screen reading primitives
-- -----------------------------------------------------------------------

local function read_char(x, y)
    local pen = dfhack.screen.readTile(x, y)
    if not pen then return " " end
    local ch = pen.ch
    if type(ch) == "number" then
        if ch >= 32 and ch < 127 then return string.char(ch) end
        return "."
    end
    return ch or " "
end

local function build_screen_text()
    local w, h = dfhack.screen.getWindowSize()
    local lines = {}
    for y = 0, h - 1 do
        local row = {}
        for x = 0, w - 1 do
            row[#row + 1] = read_char(x, y)
        end
        lines[y] = table.concat(row)
    end
    return lines, w, h
end

local function find_text(target)
    local lines, w, h = build_screen_text()
    local results = {}
    for y = 0, h - 1 do
        local line = lines[y]
        local pos = 1
        while true do
            local s, e = line:find(target, pos, true)
            if not s then break end
            table.insert(results, {
                x = s - 1,
                y = y,
                click_x = s - 1 + math.floor((e - s) / 2),
                click_y = y,
            })
            pos = e + 1
        end
    end
    return results
end

local function get_focus()
    local focus = dfhack.gui.getCurFocus()
    return focus and focus[1] or "unknown"
end

-- -----------------------------------------------------------------------
-- Click primitives
-- -----------------------------------------------------------------------

local function click_at(x, y)
    local scr = dfhack.gui.getCurViewscreen()
    df.global.gps.mouse_x = x
    df.global.gps.mouse_y = y
    df.global.enabler.tracking_on = 1
    gui.simulateInput(scr, "_MOUSE_L")
end

-- Find text on screen and click it. Returns true + coords if found.
local function click_text(target)
    local results = find_text(target)
    if #results == 0 then return false end
    local r = results[1]
    click_at(r.click_x, r.click_y)
    return true, r.click_x, r.click_y
end

-- -----------------------------------------------------------------------
-- Reliable navigation: click with retry and verification
-- -----------------------------------------------------------------------

-- Click a button, retry up to max_attempts with frame delays.
-- Returns true if button was found and clicked.
local function click_with_retry(target, max_attempts, delay_frames)
    max_attempts = max_attempts or 5
    delay_frames = delay_frames or 3
    local attempt = 0

    local function try_click()
        attempt = attempt + 1
        local ok, cx, cy = click_text(target)
        if ok then
            dfhack.println(("[nav] Clicked '%s' at (%d,%d) on attempt %d"):format(
                target, cx, cy, attempt))
            return true
        end
        if attempt < max_attempts then
            dfhack.timeout(delay_frames, "frames", try_click)
        else
            dfhack.printerr(("[nav] '%s' not found after %d attempts"):format(target, attempt))
        end
        return false
    end

    return try_click()
end

-- Wait for focus to match a prefix. Polls every poll_frames.
-- Calls callback(focus_string) when matched, or on_timeout() after timeout_frames.
local function wait_for_focus(prefix, callback, timeout_frames, poll_frames, on_timeout)
    timeout_frames = timeout_frames or 300  -- 5s at 60fps
    poll_frames = poll_frames or 10
    local elapsed = 0

    local function poll()
        local focus = get_focus()
        if focus:find(prefix, 1, true) then
            callback(focus)
            return
        end
        elapsed = elapsed + poll_frames
        if elapsed >= timeout_frames then
            if on_timeout then
                on_timeout(focus)
            else
                dfhack.printerr(("[nav] Timeout waiting for '%s' (stuck on '%s')"):format(prefix, focus))
            end
            return
        end
        dfhack.timeout(poll_frames, "frames", poll)
    end

    dfhack.timeout(poll_frames, "frames", poll)
end

-- Click a button, then verify the focus changes to expected_prefix.
-- Calls on_success(focus) or on_failure(focus) callback.
local function click_and_verify(target, expected_prefix, on_success, on_failure, opts)
    opts = opts or {}
    local max_attempts = opts.max_attempts or 5
    local verify_timeout = opts.verify_timeout or 300
    local verify_poll = opts.verify_poll or 10
    local retry_delay = opts.retry_delay or 5

    local attempt = 0
    local function try()
        attempt = attempt + 1
        local ok, cx, cy = click_text(target)
        if not ok then
            if attempt < max_attempts then
                dfhack.timeout(retry_delay, "frames", try)
            else
                local msg = ("[nav] '%s' not found after %d attempts"):format(target, attempt)
                dfhack.printerr(msg)
                if on_failure then on_failure(get_focus()) end
            end
            return
        end

        dfhack.println(("[nav] Clicked '%s' at (%d,%d), verifying '%s'..."):format(
            target, cx, cy, expected_prefix))

        wait_for_focus(expected_prefix,
            function(focus)
                dfhack.println(("[nav] Verified: '%s'"):format(focus))
                if on_success then on_success(focus) end
            end,
            verify_timeout,
            verify_poll,
            function(focus)
                if attempt < max_attempts then
                    dfhack.println(("[nav] Verify failed (at '%s'), retrying..."):format(focus))
                    dfhack.timeout(retry_delay, "frames", try)
                else
                    dfhack.printerr(("[nav] Failed to reach '%s' after %d attempts"):format(
                        expected_prefix, attempt))
                    if on_failure then on_failure(focus) end
                end
            end
        )
    end

    try()
end

-- -----------------------------------------------------------------------
-- Navigation tree — known transitions
-- -----------------------------------------------------------------------

-- Each entry: { screen_focus, button_text, expected_next_focus }
local NAV_TREE = {
    -- Title screen
    title_to_worldgen = {
        focus = "title",
        button = "Create new world",
        next_focus = "new_region",
    },
    title_to_continue = {
        focus = "title",
        button = "Continue",
        next_focus = "dwarfmode",
    },
    -- World gen
    worldgen_okay = {
        focus = "new_region/Basic",
        button = "Okay",
        next_focus = "new_region",  -- stays on new_region but dialog dismissed
    },
    worldgen_create = {
        focus = "new_region",
        button = "Create world",
        next_focus = "new_region",  -- starts generating (focus stays same)
    },
    -- After worldgen completes → site selection
    -- (no click needed, auto-transitions)
    -- Site selection
    site_to_embark = {
        focus = "choose_start_site",
        button = "Embark!",
        next_focus = "setupdwarfgame",
    },
    -- Embark setup
    embark_play_now = {
        focus = "setupdwarfgame",
        button = "Play Now!",
        next_focus = "setupdwarfgame",  -- shows confirmation
    },
    embark_confirm = {
        focus = "setupdwarfgame",
        button = "Embark!",
        next_focus = "dwarfmode",
    },
}

-- -----------------------------------------------------------------------
-- High-level navigation commands
-- -----------------------------------------------------------------------

local function navigate_step(step_name, callback)
    local step = NAV_TREE[step_name]
    if not step then
        dfhack.printerr(("[nav] Unknown step: %s"):format(step_name))
        return
    end

    -- Verify we're on the expected screen
    local focus = get_focus()
    if not focus:find(step.focus, 1, true) then
        dfhack.printerr(("[nav] Expected '%s' but on '%s'"):format(step.focus, focus))
        return
    end

    click_and_verify(step.button, step.next_focus,
        function(new_focus)
            if callback then callback(new_focus) end
        end,
        function(stuck_focus)
            dfhack.printerr(("[nav] Step '%s' failed, stuck on '%s'"):format(step_name, stuck_focus))
        end
    )
end

-- -----------------------------------------------------------------------
-- CLI interface
-- -----------------------------------------------------------------------

local args = {...}
local cmd = args[1] or "focus"

if cmd == "dump" then
    local lines, w, h = build_screen_text()
    print(("[screen] %dx%d"):format(w, h))
    for y = 0, h - 1 do
        local trimmed = lines[y]:match("^(.-)%s*$")
        if #trimmed:gsub("%s+", "") > 0 then
            print(("%3d|%s"):format(y, trimmed))
        end
    end

elseif cmd == "find" then
    local target = table.concat(args, " ", 2)
    if #target == 0 then qerror("Usage: hapax-df-nav find <text>") end
    local results = find_text(target)
    if #results == 0 then
        print(("[find] '%s' not found"):format(target))
    else
        for _, r in ipairs(results) do
            print(("[find] '%s' at tile (%d, %d), click (%d, %d)"):format(
                target, r.x, r.y, r.click_x, r.click_y))
        end
    end

elseif cmd == "click" then
    local target = table.concat(args, " ", 2)
    if #target == 0 then qerror("Usage: hapax-df-nav click <text>") end
    click_with_retry(target)
    dfhack.timeout(5, "frames", function()
        print(("[click] Focus after: %s"):format(get_focus()))
    end)

elseif cmd == "focus" then
    print(("[focus] %s"):format(get_focus()))
    local scr = dfhack.gui.getCurViewscreen()
    print(("[focus] viewscreen: %s"):format(tostring(scr._type)))

elseif cmd == "tree" then
    local focus = get_focus()
    print(("=== Screen: %s ==="):format(focus))
    local lines, w, h = build_screen_text()
    local visible = {}
    for y = 0, h - 1 do
        local trimmed = lines[y]:match("^(.-)%s*$")
        local content = trimmed:gsub("%s+", "")
        if #content > 2 then
            table.insert(visible, ("%3d|%s"):format(y, trimmed))
        end
    end
    print(("[tree] %d non-empty rows out of %d"):format(#visible, h))
    for _, line in ipairs(visible) do
        print(line)
    end

elseif cmd == "step" then
    local step_name = args[2]
    if not step_name then qerror("Usage: hapax-df-nav step <step_name>") end
    navigate_step(step_name)

elseif cmd == "steps" then
    print("Available navigation steps:")
    for name, step in pairs(NAV_TREE) do
        print(("  %-25s %s → [%s] → %s"):format(name, step.focus, step.button, step.next_focus))
    end

else
    print("Usage: hapax-df-nav [dump|find|click|focus|tree|step|steps] [args]")
end
