from main import resolve_admin_ids


def test_owner_added_to_admins():
    ids = resolve_admin_ids("111,222", "1115719673")
    assert ids == [111, 222, 1115719673]


def test_owner_not_duplicated_if_already_admin():
    ids = resolve_admin_ids("111,1115719673", "1115719673")
    assert ids == [111, 1115719673]


def test_no_owner_leaves_admins_unchanged():
    assert resolve_admin_ids("111,222", "") == [111, 222]
    assert resolve_admin_ids("111,222", None) == [111, 222]


def test_owner_only_when_admins_empty():
    assert resolve_admin_ids("", "1115719673") == [1115719673]


def test_spaces_tolerated():
    assert resolve_admin_ids(" 111 , 222 ", " 333 ") == [111, 222, 333]
