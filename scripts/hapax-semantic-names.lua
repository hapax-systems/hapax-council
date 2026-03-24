-- hapax-semantic-names.lua
-- Applies Hapax semantic identities to fortress dwarves
-- Reads profiles from dfhack-config/hapax/profiles.json
-- Hooks: onMapLoad (embark), onUnitNewActive (migrants)

local json = require("json")
local eventful = require("plugins.eventful")

local PROFILES_PATH = dfhack.getDFPath() .. "/dfhack-config/hapax/profiles.json"
local GLOBAL_KEY = "hapax-semantic-names"
local profiles_cache = nil

local function load_profiles()
    if profiles_cache then return profiles_cache end
    local ok, data = pcall(json.decode_file, PROFILES_PATH)
    if ok then
        profiles_cache = data
        return data
    end
    dfhack.printerr("[hapax] Failed to load profiles: " .. tostring(data))
    return nil
end

local function pick_profile(unit)
    local profiles = load_profiles()
    if not profiles or #profiles == 0 then return nil end
    local idx = (unit.id % #profiles) + 1
    return profiles[idx]
end

local function apply_identity(unit)
    if not unit or not dfhack.units.isCitizen(unit) then return end
    if not unit.status.current_soul then return end
    if unit.name.nickname ~= "" then return end

    local profile = pick_profile(unit)
    if not profile then return end

    dfhack.units.setNickname(unit, profile.nickname or "Unnamed")
    dfhack.println(("[hapax] Named citizen %d: %s"):format(unit.id, profile.nickname or "?"))
end

local function apply_all()
    local citizens = dfhack.units.getCitizens(true)
    for _, unit in ipairs(citizens) do
        apply_identity(unit)
    end
end

local function register_hooks()
    eventful.enableEvent(eventful.eventType.UNIT_NEW_ACTIVE, 1)
    eventful.onUnitNewActive[GLOBAL_KEY] = function(unit_id)
        dfhack.timeout(5, "frames", function()
            local unit = df.unit.find(unit_id)
            if unit then apply_identity(unit) end
        end)
    end
end

if not dfhack_flags.module then
    apply_all()
    register_hooks()
    dfhack.println("[hapax] Semantic names applied. Migrant hook registered.")
end
