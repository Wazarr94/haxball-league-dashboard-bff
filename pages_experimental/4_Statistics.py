import io
from typing import Optional

import pandas as pd
import polars as pl
import streamlit as st
from prisma import Prisma
from prisma.models import LeagueDivision, LeagueMatch, LeaguePlayer, LeagueTeam
from st_pages import add_indentation

from utils.constants import GAME_TIME, TEAM_SIZE
from utils.data import (
    get_divisions,
    get_matches,
    get_players,
    get_teams,
    init_connection,
)
from utils.utils import (
    GamePosition,
    PlayerStatSheet,
    display_gametime,
    display_pass_success,
    get_statsheet_list,
    get_unique_order,
    hide_streamlit_elements,
    is_match_played,
    sum_sheets,
)

hide_streamlit_elements()
add_indentation()


def get_div_team_select(
    divisions: list[LeagueDivision], teams: list[LeagueTeam]
) -> tuple[Optional[LeagueDivision], Optional[str]]:
    col1, col2, col3 = st.columns([3, 2, 9])
    with col1:
        div_select = st.selectbox(
            "Division",
            [None] + divisions,
            format_func=lambda d: d.name if d is not None else "All",
        )
    with col2:
        st.text("")
        st.text("")
        use_team_filter = st.checkbox("Filter team", False)
    with col3:
        if div_select is None:
            team_name_options = [t.name for t in teams]
        if use_team_filter and div_select is not None:
            team_name_options = [td.team.name for td in div_select.teams]
        else:
            team_name_options = []
        team_name_select = st.selectbox("Team", team_name_options)

    return div_select, team_name_select


def get_max_matchday_stats(
    matches: list[LeagueMatch], division: Optional[LeagueDivision]
):
    if division is None:
        return 1
    matches_div = [m for m in matches if m.leagueDivisionId == division.id]
    md_list = get_unique_order([m.matchday for m in matches_div])
    md_dict = {v: i for i, v in enumerate(md_list)}
    if len(md_dict) == 0:
        return 0
    md_val_not_played = [
        md_dict[m.matchday] for m in matches_div if not is_match_played(m)
    ]
    if len(md_val_not_played) == 0:
        return max(md_dict.values())
    min_md_val_no_play = min(set(md_val_not_played))
    return max(0, min_md_val_no_play - 1)


def filter_matches(
    matches: list[LeagueMatch],
    team_name: Optional[str],
    division: LeagueDivision,
    matchdays_select: tuple[str],
):
    if division is None:
        return matches
    matches_div = [m for m in matches if m.leagueDivisionId == division.id]
    md_list = get_unique_order([m.matchday for m in matches_div])
    md_dict = {v: i for i, v in enumerate(md_list)}
    match_list_filter = []
    for m in matches_div:
        if (
            md_dict[m.matchday] < matchdays_select[0]
            or md_dict[m.matchday] > matchdays_select[1]
        ):
            continue
        if team_name is None or any([md.team.name == team_name for md in m.detail]):
            match_list_filter.append(m)
    return match_list_filter


def get_stats(
    matches_filter: list[LeagueMatch],
    teams: list[LeagueTeam],
    players: list[LeaguePlayer],
    div_select: Optional[LeagueDivision],
    team_name_select: Optional[str],
):
    period_sheets: list[PlayerStatSheet] = []
    for m in matches_filter:
        ps_list = get_statsheet_list(players, m)
        period_sheets.extend(ps_list)
    player_sheets = sum_sheets(period_sheets)

    players_stats_id: list[LeaguePlayer] = []
    for team in teams:
        if div_select is None or div_select.id in [
            td.leagueDivisionId for td in team.divisions
        ]:
            if team_name_select is None or (
                team_name_select is not None and team.name == team_name_select
            ):
                active_players_id = [p.player.id for p in team.players if p.active]
                players_stats_id.extend(active_players_id)

    player_sheets_final = [
        ps
        for ps in player_sheets
        if ps.player is not None and ps.player.id in players_stats_id
    ]

    return player_sheets_final


def show_missing_stats(
    matches_filter: list[LeagueMatch],
    players: list[LeaguePlayer],
):
    empty_sheets: list[tuple[PlayerStatSheet, LeagueMatch]] = []
    for m in matches_filter:
        ps_list = get_statsheet_list(players, m)
        empty_ps_list = [(ps, m) for ps in ps_list if ps.player is None]
        empty_sheets.extend(empty_ps_list)

    if len(empty_sheets) == 0:
        return

    st.write("### [ADMIN] Missing stats")
    for ps, m in empty_sheets:
        st.write(
            f"- **{ps.player_name} [{ps.team.name}]**",
            f"-- in *{m.title} period {ps.period_nb}*",
        )


def download_stats(df: pd.DataFrame):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Sheet1", index=False)
    return buffer


def treat_stat(stat: pl.Expr, normalized: bool, gametime: pl.Expr):
    if normalized:
        return stat / (gametime / (GAME_TIME * 2 * 60))
    return stat


def display_options_stats():
    col1, col2, col3, col4 = st.columns([3, 3, 2, 5])
    with col1:
        st.write("")
        st.write("")
        normalize_stats = st.checkbox(
            f"Normalize stats per {GAME_TIME * 2}mn ?", value=False
        )
    with col2:
        st.write("")
        st.write("")
        filter_players_time = st.checkbox(f"Hide players with < {GAME_TIME * 2}mn ?")
    with col3:
        st.write("")
        st.write("")
        filter_position_check = st.checkbox("Filter position", False)
    with col4:
        if filter_position_check:
            positions_choose = list(range(1, TEAM_SIZE + 1))
        else:
            positions_choose = []
        filter_position = st.selectbox(
            "Position",
            positions_choose,
            format_func=lambda x: GamePosition(x).name,
        )
    return normalize_stats, filter_players_time, filter_position


def display_stat(v):
    if isinstance(v, int):
        return f"{v}"
    return f"{v:.2f}"


def style_table(styler):
    styler.format(
        subset=[
            "goals",
            "assists",
            "cs",
            "saves",
            "ownGoals",
            "passes",
            "shots",
            "shotsTarget",
            "touches",
            "kicks",
            "assists_2",
            "assists_3",
            "rebounds",
            "duels",
            "interceptions",
            "clears",
        ],
        formatter=display_stat,
    )
    styler.format(
        subset=["passSuccess"],
        formatter=display_pass_success,
    )
    styler.format(
        subset=["gametime"],
        formatter=display_gametime,
    )
    styler.format(
        subset=["gamePosition"],
        formatter=lambda g: GamePosition(g).name,
    )
    return styler


def display_stats(
    statsheets: list[PlayerStatSheet],
    normalized: bool,
    filter_players: bool,
    filter_position: int,
):
    df_json = [
        {"player": ps.player.dict(), "stats": ps.stats.dict(), "cs": ps.cs}
        for ps in statsheets
    ]
    df_pd = pd.json_normalize(df_json)
    df = pl.DataFrame(df_pd)
    if len(df) == 0:
        return
    df = (
        df.select(
            [
                pl.col("player.name"),
                pl.col("stats.gamePosition"),
                pl.col("stats.gametime").floor().cast(pl.Int64),
                treat_stat(
                    pl.col("stats.goals"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ),
                treat_stat(
                    pl.col("stats.assists"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ),
                treat_stat(
                    pl.col("cs"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ),
                treat_stat(
                    pl.col("stats.saves"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ),
                treat_stat(
                    pl.col("stats.ownGoals"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ),
                treat_stat(
                    pl.col("stats.passesAttempted"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ).alias("passes"),
                (
                    pl.col("stats.passesSuccessful") / (pl.col("stats.passesAttempted"))
                ).alias("stats.passSuccess"),
                treat_stat(
                    pl.col("stats.shots"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ),
                treat_stat(
                    pl.col("stats.shotsTarget"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ),
                treat_stat(
                    pl.col("stats.touches"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ),
                treat_stat(
                    pl.col("stats.kicks"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ),
                treat_stat(
                    pl.col("stats.secondaryAssists"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ).alias("assists_2"),
                treat_stat(
                    pl.col("stats.tertiaryAssists"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ).alias("assists_3"),
                treat_stat(
                    pl.col("stats.reboundDribbles"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ).alias("rebounds"),
                treat_stat(
                    pl.col("stats.duels"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ),
                treat_stat(
                    pl.col("stats.interceptions"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ),
                treat_stat(
                    pl.col("stats.clears"),
                    normalized,
                    pl.col("stats.gametime").floor().cast(pl.Int64),
                ),
                pl.col("stats.averagePosX"),
            ]
        )
        .filter(
            pl.when(filter_players)
            .then(pl.col("stats.gametime") >= GAME_TIME * 2 * 60)
            .otherwise(True)
        )
        .filter(
            pl.when(filter_position is not None)
            .then(pl.col("stats.gamePosition") == filter_position)
            .otherwise(True)
        )
    )
    df = df.to_pandas()
    df.columns = df.columns.str.replace("player.|stats.", "", regex=True)

    st.caption(
        "Hover on the table and click the full screen icon to see all columns at once."
        + "\n\nClick on the header to sort by a statistic."
    )

    st.dataframe(df.set_index("name").style.pipe(style_table))
    st.download_button(
        label="Download data as Excel",
        data=download_stats(df),
        file_name="FUTLIFE_stats.xlsx",
        mime="application/vnd.ms-excel",
    )


def main():
    if "db" not in st.session_state:
        db = init_connection()
        st.session_state["db"] = db

    db: Prisma = st.session_state["db"]

    matches_list = get_matches(db)
    teams_list = get_teams(db)
    divisions_list = get_divisions(db)
    players_list = get_players(db)

    matchday_options = {
        div.id: get_unique_order(
            [m.matchday for m in matches_list if m.leagueDivisionId == div.id]
        )
        for div in divisions_list
    }

    st.write("# S1 preseason statistics")

    div_select, team_name_select = get_div_team_select(divisions_list, teams_list)

    if div_select is None:
        matchdays_options_div = [1, 1]
    else:
        matchdays_options_div = matchday_options[div_select.id]
    matchdays_values = range(len(matchdays_options_div))
    matchday_max = get_max_matchday_stats(matches_list, div_select)

    matchdays_select = st.select_slider(
        "Matchdays",
        options=matchdays_values,
        value=(0, matchday_max),
        format_func=(lambda v: matchdays_options_div[v]),
    )

    match_list_filter = filter_matches(
        matches_list, team_name_select, div_select, matchdays_select
    )

    stats_players = get_stats(
        match_list_filter,
        teams_list,
        players_list,
        div_select,
        team_name_select,
    )

    normalize, filter_players, filter_position = display_options_stats()

    if (
        "authentication_status" in st.session_state
        and st.session_state["authentication_status"]
    ):
        show_missing_stats(match_list_filter, players_list)

    display_stats(stats_players, normalize, filter_players, filter_position)


if __name__ == "__main__":
    main()
