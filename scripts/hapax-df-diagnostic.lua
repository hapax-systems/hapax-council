-- hapax-df-diagnostic.lua — Debug title screen navigation
-- Run from dfhack-run: hapax-df-diagnostic

local gui = require("gui")

local title = dfhack.gui.getViewscreenByType(df.viewscreen_titlest, 0)
if not title then
    print("[diag] NOT on title screen")
    local top = dfhack.gui.getCurViewscreen()
    print("[diag] Top viewscreen: " .. tostring(top._type))
    print("[diag] Focus: " .. table.concat(dfhack.gui.getCurFocus(), ", "))
    return
end

print("[diag] Title screen found")
print("[diag]   mode: " .. tostring(title.mode))

-- Try both field names
local selected_ok, selected_val = pcall(function() return title.selected end)
local sel_menu_ok, sel_menu_val = pcall(function() return title.sel_menu_line end)
print("[diag]   title.selected: " .. (selected_ok and tostring(selected_val) or "FIELD NOT FOUND"))
print("[diag]   title.sel_menu_line: " .. (sel_menu_ok and tostring(sel_menu_val) or "FIELD NOT FOUND"))

print("[diag]   menu items: " .. #title.menu_line_id)
for i = 0, #title.menu_line_id - 1 do
    local item = title.menu_line_id[i]
    local name = "unknown"
    if item == 0 then name = "Continue"
    elseif item == 1 then name = "Start"
    elseif item == 2 then name = "NewWorld"
    elseif item == 3 then name = "TestingArena"
    elseif item == 4 then name = "Mods"
    elseif item == 5 then name = "Settings"
    elseif item == 6 then name = "AboutDF"
    elseif item == 7 then name = "Quit"
    end
    print(("[diag]     [%d] = %d (%s)"):format(i, item, name))
end

print("[diag]   has child: " .. tostring(title.child ~= nil))
if title.child then
    print("[diag]   child type: " .. tostring(title.child._type))
end

-- Now try to navigate
print("[diag] Attempting navigation...")

-- Try setting selected and sending SELECT
local target_idx = nil
local target_name = nil
for i = 0, #title.menu_line_id - 1 do
    if title.menu_line_id[i] == 2 then  -- NewWorld
        target_idx = i
        target_name = "NewWorld"
        break
    end
end

if not target_idx then
    print("[diag] NewWorld not found in menu")
    return
end

-- Set selection using whichever field exists
if sel_menu_ok then
    title.sel_menu_line = target_idx
    print("[diag] Set sel_menu_line = " .. target_idx)
end
if selected_ok then
    title.selected = target_idx
    print("[diag] Set selected = " .. target_idx)
end

-- Send SELECT
print("[diag] Sending SELECT...")
gui.simulateInput(title, "SELECT")
print("[diag] SELECT sent")

-- Check result after 5 frames
dfhack.timeout(5, "frames", function()
    local focus = dfhack.gui.getCurFocus()
    print("[diag] After SELECT, focus: " .. table.concat(focus, ", "))
    local top = dfhack.gui.getCurViewscreen()
    print("[diag] After SELECT, top screen: " .. tostring(top._type))

    -- Check if title screen state changed
    local t2 = dfhack.gui.getViewscreenByType(df.viewscreen_titlest, 0)
    if t2 then
        print("[diag] Still on title, mode=" .. t2.mode)
    else
        print("[diag] Title screen is GONE — navigation succeeded!")
    end
end)
