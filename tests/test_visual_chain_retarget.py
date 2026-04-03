"""Test that visual chain dimensions target only nodes in the 8-pass vocabulary graph."""

from agents.visual_chain import VISUAL_DIMENSIONS

# The 8-pass permanent vocabulary: noise, rd, color, drift, breath, fb, content, post
VOCABULARY_NODES = {"noise", "rd", "color", "drift", "breath", "fb", "content", "post"}


def test_all_dimension_mappings_target_vocabulary_nodes():
    for dim_name, dim in VISUAL_DIMENSIONS.items():
        for mapping in dim.parameter_mappings:
            assert mapping.technique in VOCABULARY_NODES, (
                f"{dim_name} targets '{mapping.technique}' which is not in the "
                f"8-pass vocabulary graph: {VOCABULARY_NODES}"
            )
