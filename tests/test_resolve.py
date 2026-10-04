from pipeline import resolve
from pipeline.config import normalize_subject


def test_split_team_name():
    assert resolve.split_team_name("Mission San Jose B") == ("Mission San Jose", "B")
    assert resolve.split_team_name("Lynbrook") == ("Lynbrook", None)
    assert resolve.split_team_name("Iolani 2") == ("Iolani", "B")
    assert resolve.split_team_name("JP Stevens 1") == ("JP Stevens", "A")
    assert resolve.split_team_name("Lexington (C)") == ("Lexington", "C")
    assert resolve.split_team_name("Team 2510") == ("Team 2510", None)
    assert resolve.split_team_name("Troy-A") == ("Troy", "A")


def test_norm_key_ignores_school_words():
    assert resolve.norm_key("Lynbrook High School") == resolve.norm_key("Lynbrook HS") == "lynbrook"
    assert resolve.norm_key("Thomas Jefferson HS for Sci & Tech") == "thomas jefferson for sci and tech"


def test_normalize_subject():
    assert normalize_subject("Earth & Space") == "ess"
    assert normalize_subject("ES") == "ess"
    assert normalize_subject("E") == "energy"
    assert normalize_subject("Indiv Bio") == "biology"
    assert normalize_subject("RR Chemistry") == "chemistry"
    assert normalize_subject("life") == "biology"
    assert normalize_subject("compsci") == "other"
    assert normalize_subject("Zoology") is None


def test_player_resolution_rules():
    R = resolve.Resolver.__new__(resolve.Resolver)
    R.player_merge, R.player_nosplit, R.player_rename = {}, set(), {}
    obs = [
        {"tournament_id": "t1", "season": "2024-25", "raw": "Theenash Sengupta", "team_id": "msj-a", "school_id": "msj", "composite": False},
        {"tournament_id": "t2", "season": "2024-25", "raw": "Theenash S", "team_id": "msj-a", "school_id": "msj", "composite": False},
        {"tournament_id": "t3", "season": "2024-25", "raw": "theenash sengupta", "team_id": "x-pickup", "school_id": "x-pickup", "composite": True},
        {"tournament_id": "t1", "season": "2024-25", "raw": "Andrew Li", "team_id": "a-a", "school_id": "a", "composite": False},
        {"tournament_id": "t2", "season": "2024-25", "raw": "Andrew Li", "team_id": "b-a", "school_id": "b", "composite": False},
    ]
    people, raw_to_pid = resolve._resolve_players(R, obs)
    t = {k[0]: v for k, v in raw_to_pid.items() if "heenash" in k[1]}
    assert len(set(t.values())) == 1  # full, abbreviated and lowercase on a pickup team -> one person
    li = {v for k, v in raw_to_pid.items() if k[1] == "Andrew Li"}
    assert len(li) == 2  # same name at two real schools -> two people
    pid = next(iter(set(t.values())))
    assert people[pid]["name"] == "Theenash Sengupta"
    assert people[pid]["school_id"] == "msj"


def test_clean_player_name():
    assert resolve.clean_player_name("(SCDS) Adam Akins") == "Adam Akins"
    assert resolve.clean_player_name("Theenash Sengupta#0096") == "Theenash Sengupta"
    assert resolve.clean_player_name("DELETE") is None
    assert resolve.clean_player_name("  TBD ") is None
    assert resolve.clean_player_name("Player 3") is None
    assert resolve.clean_player_name("Kian Dhawan") == "Kian Dhawan"


def test_first_name_only_rows_merge_with_unique_schoolmate():
    R = resolve.Resolver.__new__(resolve.Resolver)
    R.player_merge, R.player_nosplit, R.player_rename = {}, set(), {}
    obs = [
        {"tournament_id": "t1", "season": "2024-25", "raw": "Sohil Rathi", "team_id": "lyn-a", "school_id": "lyn", "composite": False},
        {"tournament_id": "t2", "season": "2023-24", "raw": "Sohil", "team_id": "lyn-a", "school_id": "lyn", "composite": False},
        {"tournament_id": "t3", "season": "2020-21", "raw": "Daniel", "team_id": "lyn-b", "school_id": "lyn", "composite": False},
        {"tournament_id": "t1", "season": "2024-25", "raw": "Daniel Li", "team_id": "lyn-a", "school_id": "lyn", "composite": False},
    ]
    people, raw_to_pid = resolve._resolve_players(R, obs)
    assert raw_to_pid[("t1", "Sohil Rathi", "lyn-a")] == raw_to_pid[("t2", "Sohil", "lyn-a")]
    # a first name seen four seasons away from the full-name player stays separate
    assert raw_to_pid[("t3", "Daniel", "lyn-b")] != raw_to_pid[("t1", "Daniel Li", "lyn-a")]
