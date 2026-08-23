"""Embedded GLSL shader sources — fallback when shader files aren't on disk.

Each entry maps ``"<name>.vert"`` or ``"<name>.frag"`` to the full source.
"""

from __future__ import annotations

EMBEDDED_SHADERS: dict[str, str] = {}

# =========================================================================
# mesh.vert — Standard vertex transform with position, normal, uv, color
# =========================================================================
EMBEDDED_SHADERS["mesh.vert"] = """#version 330 core

layout (location = 0) in vec3 in_position;
layout (location = 1) in vec3 in_normal;
layout (location = 2) in vec2 in_uv;
layout (location = 3) in vec4 in_color;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_projection;

out vec3 v_normal;
out vec3 v_position;
out vec2 v_uv;
out vec4 v_color;

void main() {
    vec4 world_pos = u_model * vec4(in_position, 1.0);
    gl_Position = u_projection * u_view * world_pos;
    v_normal = mat3(u_model) * in_normal;
    v_position = world_pos.xyz;
    v_uv = in_uv;
    v_color = in_color;
}
"""

# =========================================================================
# mesh.frag — Basic fragment shader with uniform colour + vertex colour
# =========================================================================
EMBEDDED_SHADERS["mesh.frag"] = """#version 330 core

in vec3 v_normal;
in vec3 v_position;
in vec2 v_uv;
in vec4 v_color;

uniform vec4 u_color = vec4(1.0, 1.0, 1.0, 1.0);
uniform vec3 u_light_dir = vec3(0.5, 1.0, 0.5);
uniform float u_ambient = 0.3;
uniform int u_wireframe = 0;

out vec4 frag_color;

void main() {
    vec3 N = normalize(v_normal);
    vec3 L = normalize(u_light_dir);
    float diff = max(dot(N, L), 0.0);
    float lighting = u_ambient + (1.0 - u_ambient) * diff;
    vec4 base = u_color * v_color;
    frag_color = vec4(base.rgb * lighting, base.a);
}
"""

# =========================================================================
# grid.vert — Simple grid vertex shader
# =========================================================================
EMBEDDED_SHADERS["grid.vert"] = """#version 330 core

layout (location = 0) in vec3 in_position;

uniform mat4 u_view;
uniform mat4 u_projection;

void main() {
    gl_Position = u_projection * u_view * vec4(in_position, 1.0);
}
"""

# =========================================================================
# grid.frag — Grid pattern on the ground plane
# =========================================================================
EMBEDDED_SHADERS["grid.frag"] = """#version 330 core

uniform vec3 u_grid_color = vec3(0.3, 0.3, 0.3);
uniform vec3 u_axis_color = vec3(0.5, 0.5, 0.5);
uniform float u_fade_distance = 50.0;

in vec3 v_world_pos;
out vec4 frag_color;

void main() {
    float x = abs(v_world_pos.x);
    float z = abs(v_world_pos.z);

    float dx = fwidth(v_world_pos.x);
    float dz = fwidth(v_world_pos.z);

    float dist = length(v_world_pos.xz);
    float fade = clamp(1.0 - dist / u_fade_distance, 0.0, 1.0);

    float line_x = 1.0 - smoothstep(0.0, dx * 2.0, abs(round(v_world_pos.x) - v_world_pos.x));
    float line_z = 1.0 - smoothstep(0.0, dz * 2.0, abs(round(v_world_pos.z) - v_world_pos.z));

    float grid = max(line_x, line_z) * fade;
    float is_axis = 0.0;
    if (abs(v_world_pos.x) < dx * 4.0 || abs(v_world_pos.z) < dz * 4.0) {
        is_axis = 1.0;
    }

    vec3 color = mix(u_grid_color, u_axis_color, is_axis);
    frag_color = vec4(color, grid * 0.8);
}
"""

# =========================================================================
# background.vert — Full-screen quad for background pass
# =========================================================================
EMBEDDED_SHADERS["background.vert"] = """#version 330 core

layout (location = 0) in vec2 in_position;
layout (location = 1) in vec2 in_uv;

out vec2 v_uv;

void main() {
    gl_Position = vec4(in_position, 0.0, 1.0);
    v_uv = in_uv;
}
"""

# =========================================================================
# background.frag — Gradient background
# =========================================================================
EMBEDDED_SHADERS["background.frag"] = """#version 330 core

uniform vec3 u_color_top = vec3(0.08, 0.08, 0.12);
uniform vec3 u_color_bottom = vec3(0.18, 0.18, 0.22);
uniform int u_gradient = 1;

in vec2 v_uv;
out vec4 frag_color;

void main() {
    vec3 color = mix(u_color_bottom, u_color_top, v_uv.y);
    if (u_gradient == 0) {
        color = u_color_bottom;
    }
    frag_color = vec4(color, 1.0);
}
"""

# =========================================================================
# overlay.vert — 2D overlay / text rendering vertex shader
# =========================================================================
EMBEDDED_SHADERS["overlay.vert"] = """#version 330 core

layout (location = 0) in vec2 in_position;
layout (location = 1) in vec4 in_color;
layout (location = 2) in vec2 in_uv;

uniform vec2 u_viewport_size;

out vec4 v_color;
out vec2 v_uv;

void main() {
    vec2 ndc = (in_position / u_viewport_size) * 2.0 - 1.0;
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_color = in_color;
    v_uv = in_uv;
}
"""

# =========================================================================
# overlay.frag — Simple overlay fragment shader
# =========================================================================
EMBEDDED_SHADERS["overlay.frag"] = """#version 330 core

in vec4 v_color;
in vec2 v_uv;

uniform sampler2D u_texture;
uniform int u_has_texture = 0;

out vec4 frag_color;

void main() {
    if (u_has_texture == 1) {
        frag_color = texture(u_texture, v_uv) * v_color;
    } else {
        frag_color = v_color;
    }
}
"""

# =========================================================================
# selection.vert — Selection highlight vertex shader
# =========================================================================
EMBEDDED_SHADERS["selection.vert"] = """#version 330 core

layout (location = 0) in vec3 in_position;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_projection;

void main() {
    gl_Position = u_projection * u_view * u_model * vec4(in_position, 1.0);
}
"""

# =========================================================================
# selection.frag — Selection highlight / outline
# =========================================================================
EMBEDDED_SHADERS["selection.frag"] = """#version 330 core

uniform vec4 u_selection_color = vec4(0.0, 0.6, 1.0, 0.3);

out vec4 frag_color;

void main() {
    frag_color = u_selection_color;
}
"""

# =========================================================================
# debug.vert — Debug rendering (bounding boxes, normals)
# =========================================================================
EMBEDDED_SHADERS["debug.vert"] = """#version 330 core

layout (location = 0) in vec3 in_position;
layout (location = 1) in vec4 in_color;

uniform mat4 u_view;
uniform mat4 u_projection;

out vec4 v_color;

void main() {
    gl_Position = u_projection * u_view * vec4(in_position, 1.0);
    v_color = in_color;
}
"""

# =========================================================================
# debug.frag — Simple flat-colour debug shader
# =========================================================================
EMBEDDED_SHADERS["debug.frag"] = """#version 330 core

in vec4 v_color;
out vec4 frag_color;

void main() {
    frag_color = v_color;
}
"""

# =========================================================================
# axis_gizmo.vert — 3D axis gizmo
# =========================================================================
EMBEDDED_SHADERS["axis_gizmo.vert"] = """#version 330 core

layout (location = 0) in vec3 in_position;
layout (location = 1) in vec4 in_color;

uniform mat4 u_view;
uniform mat4 u_projection;
uniform float u_scale = 1.0;

out vec4 v_color;

void main() {
    gl_Position = u_projection * u_view * vec4(in_position * u_scale, 1.0);
    v_color = in_color;
}
"""

# =========================================================================
# axis_gizmo.frag — Pass-through colour
# =========================================================================
EMBEDDED_SHADERS["axis_gizmo.frag"] = """#version 330 core

in vec4 v_color;
out vec4 frag_color;

void main() {
    frag_color = v_color;
}
"""

# =========================================================================
# fullscreen.vert — Full-screen triangle/quad for post-processing
# =========================================================================
EMBEDDED_SHADERS["fullscreen.vert"] = """#version 330 core

layout (location = 0) in vec2 in_position;
layout (location = 1) in vec2 in_uv;

out vec2 v_uv;

void main() {
    gl_Position = vec4(in_position, 0.0, 1.0);
    v_uv = in_uv;
}
"""

# =========================================================================
# fullscreen.frag — Passthrough texture display
# =========================================================================
EMBEDDED_SHADERS["fullscreen.frag"] = """#version 330 core

uniform sampler2D u_texture;

in vec2 v_uv;
out vec4 frag_color;

void main() {
    frag_color = texture(u_texture, v_uv);
}
"""

# =========================================================================
# projection.vert — Vertex shader for warp mesh
# =========================================================================
EMBEDDED_SHADERS["projection.vert"] = """#version 330 core
// Projection vertex shader — applies warp mesh to content texture
layout(location = 0) in vec2 in_position;  // Projector UV (clip space position)
layout(location = 1) in vec2 in_uv;        // Content UV (texture coordinate)

out vec2 v_uv;

void main() {
    gl_Position = vec4(in_position, 0.0, 1.0);
    v_uv = in_uv;
}
"""

# =========================================================================
# projection.frag — Fragment shader with blend/mask/crop
# =========================================================================
EMBEDDED_SHADERS["projection.frag"] = """#version 330 core
// Projection fragment shader — samples warped content with blend/mask/crop
uniform sampler2D u_texture;
uniform vec4 u_crop;        // x, y, width, height (normalized 0-1)
uniform float u_blend;      // blend opacity (0.0 = transparent, 1.0 = opaque)
uniform int u_mask_enabled; // 0 = no mask, 1 = mask active
uniform vec2 u_mask_center; // mask center (normalized 0-1)
uniform float u_mask_radius; // mask radius (normalized 0-1)

in vec2 v_uv;
out vec4 fragColor;

void main() {
    // Crop: discard pixels outside crop region
    if (v_uv.x < u_crop.x || v_uv.x > u_crop.x + u_crop.z ||
        v_uv.y < u_crop.y || v_uv.y > u_crop.y + u_crop.w) {
        discard;
    }

    // Sample content texture
    vec4 color = texture(u_texture, v_uv);

    // Mask: feather edges
    if (u_mask_enabled == 1) {
        float dist = distance(v_uv, u_mask_center);
        float feather = 1.0 - smoothstep(u_mask_radius * 0.8, u_mask_radius, dist);
        color.a *= feather;
    }

    // Blend: apply opacity
    color.a *= u_blend;

    fragColor = color;
}
"""
