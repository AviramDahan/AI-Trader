"""Creation gate only. Never consult this when processing a stored contract."""
import os

# The bridge release handles V2 state but cannot originate it, even if an old
# environment accidentally contains the activation flag. The activation release
# changes only this capability and the required schema floor.
CREATION_CAPABLE = True


def enabled():
    return CREATION_CAPABLE and os.getenv('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED', 'false').lower() == 'true'
