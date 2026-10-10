"""Dynamic caller references owned by shared.encountered_machinery_audit."""

# ENCOUNTERED-MACHINERY auditor. The pure evaluation module is called only by the extensionless
# producer `scripts/hapax-encountered-machinery-audit` (declared in
# config/determination-producers.json and run by hapax-determine). Vulture does not scan that
# script.
from shared.encountered_machinery_audit import Trend as _EmaTrend  # noqa: E402
from shared.encountered_machinery_audit import (  # noqa: E402
    parse_catalogue as _ema_parse_catalogue,
)
from shared.encountered_machinery_audit import (  # noqa: E402
    parse_ledger as _ema_parse_ledger,
)
from shared.encountered_machinery_audit import (  # noqa: E402
    render_flag_drop as _ema_render_flag_drop,
)
from shared.encountered_machinery_audit import (  # noqa: E402
    render_pile_status as _ema_render_pile_status,
)
from shared.encountered_machinery_audit import (  # noqa: E402
    render_reduction_row as _ema_render_reduction_row,
)
from shared.encountered_machinery_audit import (  # noqa: E402
    split_frontmatter as _ema_split_frontmatter,
)

_ = (
    _EmaTrend.unobserved,
    _ema_parse_catalogue,
    _ema_parse_ledger,
    _ema_render_flag_drop,
    _ema_render_pile_status,
    _ema_render_reduction_row,
    _ema_split_frontmatter,
)
