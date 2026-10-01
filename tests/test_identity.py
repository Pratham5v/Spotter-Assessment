from stations.identity import station_name


def test_preserve_operator_and_branch_reference():
    assert station_name("FLYING J TRAVEL PLAZA #665") == ("Flying J", "665")
    assert station_name("LOVES TRAVEL STOP #752") == ("Love's", "752")
