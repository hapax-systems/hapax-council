-- GENERATED: Hapax WirePlumber link-time deny hook.
-- Source: shared.audio_routing_policy.generated_wireplumber_deny_policy_texts
-- Policy data: embedded from generated forbidden route policy.
-- Do not hand-edit; run scripts/generate-pipewire-audio-confs.py --write-wireplumber-deny-policy.
--
-- Four-layer fail-closed behavior:
--   1. Reject forbidden node-pair auto-targets before WirePlumber link-target.
--   2. Remove exact forbidden port links if a client creates one directly.
--   3. Deny optional-device fallback into Polyend capture unless source is Polyend.
--   4. Carry the generated forbidden policy inside the Lua artifact so
--      WirePlumber's sandbox cannot lose the policy through missing file I/O.

lutils = require ("linking-utils")
log = Log.open_topic ("s-linking.hapax-deny")

local FAIL_CLOSED_FORBIDDEN_LINKS = {
  ["hapax-private-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FL"] = true,
  ["hapax-private-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FR"] = true,
  ["hapax-private-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RL"] = true,
  ["hapax-private-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RR"] = true,
  ["hapax-private-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FL"] = true,
  ["hapax-private-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FR"] = true,
  ["hapax-private-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RL"] = true,
  ["hapax-private-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RR"] = true,
  ["hapax-notification-private-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FL"] = true,
  ["hapax-notification-private-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FR"] = true,
  ["hapax-notification-private-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RL"] = true,
  ["hapax-notification-private-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RR"] = true,
  ["hapax-notification-private-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FL"] = true,
  ["hapax-notification-private-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FR"] = true,
  ["hapax-notification-private-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RL"] = true,
  ["hapax-notification-private-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RR"] = true,
  ["hapax-pc-loudnorm-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FL"] = true,
  ["hapax-pc-loudnorm-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FR"] = true,
  ["hapax-pc-loudnorm-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RL"] = true,
  ["hapax-pc-loudnorm-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RR"] = true,
  ["hapax-pc-loudnorm-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FL"] = true,
  ["hapax-pc-loudnorm-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FR"] = true,
  ["hapax-pc-loudnorm-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RL"] = true,
  ["hapax-pc-loudnorm-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RR"] = true,
  ["hapax-loudnorm-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FL"] = true,
  ["hapax-loudnorm-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FR"] = true,
  ["hapax-loudnorm-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RL"] = true,
  ["hapax-loudnorm-playback:output_FL|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RR"] = true,
  ["hapax-loudnorm-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FL"] = true,
  ["hapax-loudnorm-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FR"] = true,
  ["hapax-loudnorm-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RL"] = true,
  ["hapax-loudnorm-playback:output_FR|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_RR"] = true,
  ["hapax-pc-loudnorm-playback:output_FL|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0:playback_AUX4"] = true,
  ["hapax-pc-loudnorm-playback:output_FR|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0:playback_AUX5"] = true,
  ["hapax-yt-loudnorm-playback:output_FL|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0:playback_AUX6"] = true,
  ["hapax-yt-loudnorm-playback:output_FR|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0:playback_AUX7"] = true,
  ["hapax-notification-private-playback:output_FL|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0:playback_AUX8"] = true,
  ["hapax-notification-private-playback:output_FR|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0:playback_AUX9"] = true,
  ["hapax-m8-loudnorm-playback:output_AUX10|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0:playback_AUX10"] = true,
  ["hapax-m8-loudnorm-playback:output_AUX11|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0:playback_AUX11"] = true,
  ["hapax-pc-loudnorm-playback:output_FL|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output:playback_AUX4"] = true,
  ["hapax-pc-loudnorm-playback:output_FR|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output:playback_AUX5"] = true,
  ["hapax-yt-loudnorm-playback:output_FL|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output:playback_AUX6"] = true,
  ["hapax-yt-loudnorm-playback:output_FR|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output:playback_AUX7"] = true,
  ["hapax-notification-private-playback:output_FL|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output:playback_AUX8"] = true,
  ["hapax-notification-private-playback:output_FR|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output:playback_AUX9"] = true,
  ["hapax-m8-loudnorm-playback:output_AUX10|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output:playback_AUX10"] = true,
  ["hapax-m8-loudnorm-playback:output_AUX11|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output:playback_AUX11"] = true,
  ["hapax-m8-loudnorm-playback:output_AUX10|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FL"] = true,
  ["hapax-m8-loudnorm-playback:output_AUX11|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FR"] = true,
  ["hapax-tts-broadcast-playback:output_FL|hapax-livestream-tap:playback_FL"] = true,
  ["hapax-tts-broadcast-playback:output_FR|hapax-livestream-tap:playback_FR"] = true,
  ["hapax-s4-tap:output_FL|hapax-livestream-tap:playback_FL"] = true,
  ["hapax-s4-tap:output_FR|hapax-livestream-tap:playback_FR"] = true,
  ["hapax-livestream:monitor_FL|hapax-broadcast-master-capture:input_FL"] = true,
  ["hapax-livestream:monitor_FR|hapax-broadcast-master-capture:input_FR"] = true,
  ["output.loopback.sink.role.assistant:output_FL|input.loopback.sink.role.multimedia:playback_FL"] = true,
  ["output.loopback.sink.role.assistant:output_FR|input.loopback.sink.role.multimedia:playback_FR"] = true,
  ["input.loopback.sink.role.assistant-output:output_FL|input.loopback.sink.role.multimedia:playback_FL"] = true,
  ["input.loopback.sink.role.assistant-output:output_FR|input.loopback.sink.role.multimedia:playback_FR"] = true,
  ["output.loopback.sink.role.notification:output_FL|input.loopback.sink.role.multimedia:playback_FL"] = true,
  ["output.loopback.sink.role.notification:output_FR|input.loopback.sink.role.multimedia:playback_FR"] = true,
  ["input.loopback.sink.role.notification-output:output_FL|input.loopback.sink.role.multimedia:playback_FL"] = true,
  ["input.loopback.sink.role.notification-output:output_FR|input.loopback.sink.role.multimedia:playback_FR"] = true,
}

local FAIL_CLOSED_BOUNDARY_PAIRS = {
  ["hapax-private-playback|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40"] = true,
  ["hapax-notification-private-playback|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40"] = true,
  ["hapax-pc-loudnorm-playback|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40"] = true,
  ["hapax-loudnorm-playback|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40"] = true,
  ["hapax-pc-loudnorm-playback|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0"] = true,
  ["hapax-yt-loudnorm-playback|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0"] = true,
  ["hapax-notification-private-playback|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0"] = true,
  ["hapax-m8-loudnorm-playback|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0"] = true,
  ["hapax-pc-loudnorm-playback|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"] = true,
  ["hapax-yt-loudnorm-playback|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"] = true,
  ["hapax-notification-private-playback|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"] = true,
  ["hapax-m8-loudnorm-playback|alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"] = true,
  ["hapax-m8-loudnorm-playback|alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40"] = true,
  ["hapax-tts-broadcast-playback|hapax-livestream-tap"] = true,
  ["hapax-s4-tap|hapax-livestream-tap"] = true,
  ["hapax-livestream|hapax-broadcast-master-capture"] = true,
  ["output.loopback.sink.role.assistant|input.loopback.sink.role.multimedia"] = true,
  ["input.loopback.sink.role.assistant-output|input.loopback.sink.role.multimedia"] = true,
  ["output.loopback.sink.role.notification|input.loopback.sink.role.multimedia"] = true,
  ["input.loopback.sink.role.notification-output|input.loopback.sink.role.multimedia"] = true,
}

local function load_forbidden_policy ()
  return {
    links = FAIL_CLOSED_FORBIDDEN_LINKS,
    node_pairs = FAIL_CLOSED_BOUNDARY_PAIRS,
    degraded = false,
  }
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

local function anonymous_loopback_to_multimedia_denied (source_node, target_node)
  return source_node ~= nil
      and target_node == "input.loopback.sink.role.multimedia"
      and string.match (source_node, "^output%.loopback%-%d+%-%d+$") ~= nil
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
    local dynamic_denied = anonymous_loopback_to_multimedia_denied (source_node, target_node)
    if not policy.node_pairs [pair_key]
        and not optional_device_fallback_denied (source_node, target_node)
        and not dynamic_denied then
      return
    end

    local node = si:get_associated_proxy ("node")
    local message = "hapax forbidden audio route: " .. source_node .. " -> " .. target_node
    if dynamic_denied then
      message = message .. " [dynamic anonymous-loopback boundary]"
    end
    if policy.degraded then
      message = message .. " [DEGRADED: runtime policy missing, boundary deny active]"
    end
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
    local pair_key = nil
    if source_node ~= nil and target_node ~= nil then
      pair_key = source_node .. "|" .. target_node
    end
    local optional_denied = optional_device_fallback_denied (source_node, target_node)
    local dynamic_denied = anonymous_loopback_to_multimedia_denied (source_node, target_node)
    if key == nil and pair_key == nil and not optional_denied and not dynamic_denied then
      return
    end

    local policy = load_forbidden_policy ()
    local link_denied = key ~= nil and policy.links [key]
    local pair_denied = pair_key ~= nil and policy.node_pairs [pair_key]
    if not link_denied and not pair_denied and not optional_denied and not dynamic_denied then
      return
    end

    local message = "removing hapax forbidden audio link " .. tostring (key)
    if pair_denied and not link_denied then
      message = message .. " (node boundary " .. tostring (pair_key) .. ")"
    end
    if dynamic_denied then
      message = message .. " (dynamic anonymous-loopback boundary)"
    end
    if policy.degraded then
      message = message .. " [DEGRADED: runtime policy missing, boundary deny active]"
    end
    log:warning (link, message)
    link:remove ()
  end
}:register ()
