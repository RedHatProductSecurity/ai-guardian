"""Select displayed pause rows without opening a desktop."""


def pause_values(
    snapshot, *, daemon=0, scope="global", identity="", action="Pause", minutes=5
):
    view = snapshot.views[daemon]
    option = view.find(scope, identity)
    assert option is not None
    token = next(
        token for token, (v, o) in snapshot.rows.items() if v is view and o is option
    )
    return {"row": token, "action": action, "minutes": minutes}


def row_event(
    payload, *, daemon=0, scope="global", target=None, action="Pause", minutes=5
):
    rows = payload["rows"]
    starts = [index for index, row in enumerate(rows) if row["level"] == 0]
    start = starts[daemon]
    end = starts[daemon + 1] if daemon + 1 < len(starts) else len(rows)
    row = next(
        row
        for row in rows[start:end]
        if row["scope"] == scope
        and row["available"]
        and (target is None or target in row["label"])
    )
    assert row["action"] == action
    return {"row": row["id"], "action": action, "minutes": minutes}
