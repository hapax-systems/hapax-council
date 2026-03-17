// Physarum agent simulation — sense, rotate, move, deposit
// Each agent has: position (x,y), heading angle, speed

struct Params {
    width: u32,
    height: u32,
    agent_count: u32,
    sensor_angle: f32,   // radians (default: 0.3927 = 22.5°)
    sensor_dist: f32,    // pixels (default: 9.0)
    turn_speed: f32,     // radians/step (default: 0.3)
    move_speed: f32,     // pixels/step (default: 1.0)
    deposit_amount: f32, // trail deposit (default: 5.0)
    time: f32,
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
}

struct Agent {
    x: f32,
    y: f32,
    angle: f32,
    _pad: f32,
}

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var<storage, read_write> agents: array<Agent>;
@group(0) @binding(2) var trail_map: texture_2d<f32>;
@group(0) @binding(3) var deposit_map: texture_storage_2d<r32float, read_write>;

// PCG hash for randomness
fn pcg_hash(input: u32) -> u32 {
    var state = input * 747796405u + 2891336453u;
    var word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

fn rand_f32(seed: u32) -> f32 {
    return f32(pcg_hash(seed)) / 4294967295.0;
}

fn sense(agent: Agent, angle_offset: f32) -> f32 {
    let sense_angle = agent.angle + angle_offset;
    let sense_x = agent.x + cos(sense_angle) * params.sensor_dist;
    let sense_y = agent.y + sin(sense_angle) * params.sensor_dist;
    let ix = clamp(i32(sense_x), 0, i32(params.width) - 1);
    let iy = clamp(i32(sense_y), 0, i32(params.height) - 1);
    return textureLoad(trail_map, vec2<i32>(ix, iy), 0).x;
}

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let idx = gid.x;
    if idx >= params.agent_count {
        return;
    }

    var agent = agents[idx];

    // Sense: left, center, right
    let sense_left = sense(agent, -params.sensor_angle);
    let sense_center = sense(agent, 0.0);
    let sense_right = sense(agent, params.sensor_angle);

    // Random factor for stochastic turning
    let rng = rand_f32(idx + u32(params.time * 1000.0));

    // Rotate based on sensory input
    if sense_center > sense_left && sense_center > sense_right {
        // Continue straight (no turn)
    } else if sense_center < sense_left && sense_center < sense_right {
        // Turn randomly
        if rng > 0.5 {
            agent.angle += params.turn_speed;
        } else {
            agent.angle -= params.turn_speed;
        }
    } else if sense_right > sense_left {
        agent.angle += params.turn_speed;
    } else if sense_left > sense_right {
        agent.angle -= params.turn_speed;
    }

    // Move
    let new_x = agent.x + cos(agent.angle) * params.move_speed;
    let new_y = agent.y + sin(agent.angle) * params.move_speed;

    // Wrap around boundaries
    agent.x = new_x - floor(new_x / f32(params.width)) * f32(params.width);
    agent.y = new_y - floor(new_y / f32(params.height)) * f32(params.height);

    agents[idx] = agent;

    // Deposit trail
    let px = clamp(i32(agent.x), 0, i32(params.width) - 1);
    let py = clamp(i32(agent.y), 0, i32(params.height) - 1);
    let pos = vec2<i32>(px, py);
    let current = textureLoad(deposit_map, pos).x;
    textureStore(deposit_map, pos, vec4<f32>(current + params.deposit_amount, 0.0, 0.0, 1.0));
}
