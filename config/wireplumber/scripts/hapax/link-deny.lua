-- GENERATED: Hapax WirePlumber link-time deny hook.
-- Source: shared.audio_routing_policy.generated_wireplumber_deny_policy_texts
-- Runtime policy data: ~/.config/hapax/audio-forbidden-links.conf
-- Do not hand-edit; run scripts/generate-pipewire-audio-confs.py --write-wireplumber-deny-policy.
--
-- Two-layer fail-closed behavior:
--   1. Reject forbidden node-pair auto-targets before WirePlumber link-target.
--   2. Remove exact forbidden port links if a client creates one directly.
--   3. Deny optional-device fallback into Polyend capture unless source is Polyend.

lutils = require ("linking-utils")
log = Log.open_topic ("s-linking.hapax-deny")

local forbidden_path = os.getenv ("HAPAX_AUDIO_FORBIDDEN_LINKS")
if forbidden_path == nil or forbidden_path == "" then
  local home = os.getenv ("HOME") or "/home/hapax"
  forbidden_path = home .. "/.config/hapax/audio-forbidden-links.conf"
end

local function trim_policy_line (line)
  line = string.gsub (line, "#.*$", "")
  line = string.gsub (line, "^%s+", "")
  line = string.gsub (line, "%s+$", "")
  return line
end

local function load_forbidden_policy ()
  local policy = { links = {}, node_pairs = {} }
  local file = io.open (forbidden_path, "r")
  if file == nil then
    log:warning ("forbidden link map not found: " .. tostring (forbidden_path))
    return policy
  end

  for raw in file:lines () do
    local line = trim_policy_line (raw)
    if line ~= "" then
      policy.links [line] = true
      local source_node, _, target_node =
          string.match (line, "^([^:]+):([^|]+)|([^:]+):(.+)$")
      if source_node ~= nil and target_node ~= nil then
        policy.node_pairs [source_node .. "|" .. target_node] = true
      end
    end
  end
  file:close ()
  return policy
end

local function lookup_bound (source, manager_name, bound_id)
  if source == nil or bound_id == nil then
    return nil
  end
  local om = source:call ("get-object-manager", manager_name)
  if om == nil then
    return nil
  end
  return om:lookup {
    Constraint { "bound-id", "=", tonumber (bound_id), type = "gobject" },
  }
end

local function node_name (source, node_id)
  local node = lookup_bound (source, "node", node_id)
  if node == nil then
    return nil
  end
  return node.properties ["node.name"]
end

local function port_name (source, port_id)
  local port = lookup_bound (source, "port", port_id)
  if port == nil then
    return nil
  end
  return port.properties ["port.name"]
end

local function is_polyend_source (source_node)
  return source_node ~= nil and string.match (source_node, "^alsa_input%.usb%-Polyend_") ~= nil
end

local function optional_device_fallback_denied (source_node, target_node)
  return target_node == "hapax-polyend-instrument-capture" and not is_polyend_source (source_node)
end

local function link_key (source, link)
  local props = link.properties
  local source_node = node_name (source, props ["link.output.node"])
  local target_node = node_name (source, props ["link.input.node"])
  local source_port = port_name (source, props ["link.output.port"])
  local target_port = port_name (source, props ["link.input.port"])
  if source_node == nil or target_node == nil or source_port == nil or target_port == nil then
    return nil, source_node, target_node
  end
  return source_node .. ":" .. source_port .. "|" .. target_node .. ":" .. target_port,
      source_node, target_node
end

SimpleEventHook {
  name = "linking/hapax-deny-forbidden-target",
  after = "linking/prepare-link",
  before = "linking/link-target",
  interests = {
    EventInterest {
      Constraint { "event.type", "=", "select-target" },
    },
  },
  execute = function (event)
    local _, _, si, si_props, _, target = lutils:unwrap_select_target_event (event)
    if target == nil then
      return
    end

    local target_props = target.properties
    local source_node = nil
    local target_node = nil
    if si_props ["item.node.direction"] == "output" then
      source_node = si_props ["node.name"]
      target_node = target_props ["node.name"]
    else
      source_node = target_props ["node.name"]
      target_node = si_props ["node.name"]
    end

    if source_node == nil or target_node == nil then
      return
    end

    local pair_key = source_node .. "|" .. target_node
    local policy = load_forbidden_policy ()
    if not policy.node_pairs [pair_key]
        and not optional_device_fallback_denied (source_node, target_node) then
      return
    end

    local node = si:get_associated_proxy ("node")
    local message = "hapax forbidden audio route: " .. source_node .. " -> " .. target_node
    log:warning (si, message)
    event:set_data ("target", nil)
    lutils.sendClientError (event, node, -13, message)
    event:stop_processing ()
  end
}:register ()

SimpleEventHook {
  name = "linking/hapax-remove-forbidden-port-link",
  interests = {
    EventInterest {
      Constraint { "event.type", "=", "link-added" },
    },
  },
  execute = function (event)
    local source = event:get_source ()
    local link = event:get_subject ()
    local key, source_node, target_node = link_key (source, link)
    local optional_denied = optional_device_fallback_denied (source_node, target_node)
    if key == nil and not optional_denied then
      return
    end

    local policy = load_forbidden_policy ()
    if (key == nil or not policy.links [key]) and not optional_denied then
      return
    end

    log:warning (link, "removing hapax forbidden audio link " .. tostring (key))
    link:remove ()
  end
}:register ()
