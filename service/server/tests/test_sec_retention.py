import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import sec_retention


def test_no_remote_ack_is_not_a_cleanup_authorization(tmp_path):
    for commit in (None,'', 'bad', 'x'*40):
        with pytest.raises(ValueError,match='verified_remote_archive'):
            sec_retention.prune_archived('unused',tmp_path,{'remote_commit':commit})
