-- hapax-link-deny-policy.lua
-- WirePlumber link-time deny policy for audio boundary violations.
--
-- Rejects forbidden links at connect time so the reconciler daemon
-- never has to repair them. Reads the deny list from the compiled
-- forbidden-links config.
--
-- Install: copy to ~/.config/wireplumber/scripts/ (or symlink)
-- Dry-run: set HAPAX_AUDIO_DENY_DRY_RUN=1 to log without blocking
--
-- DO NOT enable live without explicit runtime authorization.
-- See: config/hapax/audio-forbidden-links.conf for the deny list.

local CONF_PATH = os.getenv("HAPAX_AUDIO_FORBIDDEN_LINKS")
    or os.getenv("HOME") .. "/.config/hapax/audio-forbidden-links.conf"
local DRY_RUN = os.getenv("HAPAX_AUDIO_DENY_DRY_RUN") == "1"

local forbidden = {}

local function load_deny_list()
    local f = io.open(CONF_PATH, "r")
    if not f then
        Log.warning("hapax-link-deny: config not found: " .. CONF_PATH)
        return
    end
    for line in f:lines() do
        line = line:match("^%s*(.-)%s*$")
        if line ~= "" and not line:match("^#") then
            forbidden[line] = true
        end
    end
    f:close()
    local count = 0
    for _ in pairs(forbidden) do count = count + 1 end
    Log.info("hapax-link-deny: loaded " .. count .. " forbidden link patterns")
end

load_deny_list()

links_om = ObjectManager {
    Interest {
        type = "link",
        Constraint { "link.output.node", "is-present" },
    }
}

links_om:connect("object-added", function(om, link)
    local props = link.properties
    local out_port = props["link.output.port"] or ""
    local in_port = props["link.input.port"] or ""
    local key = out_port .. "|" .. in_port

    if forbidden[key] then
        if DRY_RUN then
            Log.warning("hapax-link-deny [DRY-RUN]: would block " .. key)
        else
            Log.warning("hapax-link-deny: BLOCKING forbidden link " .. key)
            link:request_destroy()
        end
    end
end)

links_om:activate()
