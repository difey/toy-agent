from nano_claude.core.session import Session, resume_or_create_session, save_current, session_path


def test_resume_or_create_session_creates_new_when_none_exist(tmp_path, monkeypatch):
    import nano_claude.core.session as session_mod

    session_dir = tmp_path / "sessions"
    monkeypatch.setattr(session_mod, "SESSION_DIR", str(session_dir))
    monkeypatch.setattr(session_mod, "INDEX_FILE", str(session_dir / "index.json"))

    cwd = str(tmp_path / "project")
    session, path = resume_or_create_session(cwd)

    assert isinstance(session, Session)
    assert session.messages == []
    assert path.endswith(".json")


def test_resume_or_create_session_resumes_most_recent(tmp_path, monkeypatch):
    import nano_claude.core.session as session_mod

    session_dir = tmp_path / "sessions"
    monkeypatch.setattr(session_mod, "SESSION_DIR", str(session_dir))
    monkeypatch.setattr(session_mod, "INDEX_FILE", str(session_dir / "index.json"))

    cwd = str(tmp_path / "project")
    first_path = session_path(cwd)
    original = Session(title="existing session")
    save_current(original, first_path)
    # save_current only writes if there are messages; force a write instead.
    original.save(first_path)

    session, path = resume_or_create_session(cwd)

    assert path == first_path
    assert session.title == "existing session"
