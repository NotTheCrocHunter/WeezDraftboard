import pdb
import re
import pandas as pd
import requests
from sleeper_wrapper import Players, Drafts, League
from pathlib import Path
import time
import json
import PySimpleGUI as sg
import numpy as np
from datetime import datetime

MAX_ROWS = 17
MAX_COLS = 12

players = Players()

YEAR = datetime.today().strftime('%Y')
TODAY = datetime.today().strftime('%Y-%m-%d')

"""
Funcs for KeeperPopUp
"""


def make_pick_list():
    """
    This func reorders  the picks to be in snake-draft format.
    """
    pl = [f"{r + 1}.{c + 1}" for r in range(MAX_ROWS) for c in range(MAX_COLS)]
    pl = np.array(pl)
    pl = np.reshape(pl, (MAX_ROWS, MAX_COLS))
    pl[1::2, :] = pl[1::2, ::-1]
    pl = pl.flatten()

    return pl.tolist()


def get_mock_keepers(mock_id):
    try:
        mock_draft = Drafts(mock_id)
        return mock_draft.get_all_picks()
    except:
        sg.popup_quick_message("Error getting mock keepers")


def reset_keepers(df):
    clear_all_keepers()  # this clears the keeper_list as [] and overwrites the keepers.json with empty list
    # this resets the columns in the PP DataFrame
    k_cols = ['is_keeper', 'is_drafted', 'pick_no', 'draft_slot', 'round']
    for k in k_cols:
        df[k] = None
    return df


def save_keepers(keeper_list):
    cols = ["name", "sleeper_id", 'is_keeper', 'pick_no', 'draft_slot', 'round', 'button_text']
    keeper_list = [{k: v for k, v in keeper.items() if k in cols} for keeper in keeper_list]
    # keeper_path = Path('../sleeper-api-wrapper/data/keepers/keepers.json')
    keeper_path = Path('data/keepers/keepers.json')
    print(f"Saving {len(keeper_list)} keepers to {keeper_path}")
    Path('data/keepers').mkdir(parents=True, exist_ok=True)
    with open(keeper_path, 'w') as file:
        json.dump(keeper_list, file, indent=4)
    pass


def get_sleeper_ids(df):
    # ----- Create the search_names (all lowercase, no spaces) ------ #
    search_names = []
    remove = ['jr', 'ii', 'sr']
    for idx, row in df.iterrows():
        if row["team"] == "JAC":
            df.loc[idx, "team"] = "JAX"
        if row['name'] == "Kyle Rudolph":
            row["team"] == "TB"
        if row["team"] == "FA":
            df.loc[idx, "team"] = None
        new_name = re.sub(r'\W+', '', row['name']).lower()
        if new_name[-3:] == "iii":
            new_name = new_name[:-3]
        elif new_name[-2:] in remove:
            new_name = new_name[:-2]

        if new_name == "kennethwalker":
            new_name = "kenwalker"

        if new_name == "mitchelltrubisky":
            new_name = "mitchtrubisky"

        if new_name == "williamfullerv":
            new_name = "williamfuller"

        if new_name == "gabrieldavis":
            new_name = "gabedavis"
        search_names.append(new_name)

    df['search_full_name'] = search_names
    search_name_tuples = list(zip(df.search_full_name, df.team))

    players_df = players.get_players_df()
    players_match_df = players_df[
        players_df[['search_full_name', 'team']].apply(tuple, axis=1).isin(search_name_tuples)]
    cols_to_use = players_match_df.columns.difference(df.columns).to_list()
    cols_to_use.append("search_full_name")
    df = pd.merge(df, players_match_df[cols_to_use], how="left", on="search_full_name")
    for index, row in df.iterrows():
        if row["position"] == "DEF":
            df.loc[index, "sleeper_id"] = row["team"]
        else:
            df.loc[index, "sleeper_id"] = row["player_id"]
    match_search_names = df['search_full_name'].to_list()
    missing_search_names = [n for n in search_names if n not in match_search_names]
    if missing_search_names:
        print(f"Missing Search Names: {missing_search_names}")
    return df


def get_adp_df(adp_type="2qb", adp_year=YEAR, teams_count=12, positions="all"):
    start_time = time.time()
    adp_type = adp_type.lower()
    base_url = f"https://fantasyfootballcalculator.com/api/v1/adp/" \
               f"{adp_type}?teams={teams_count}&{adp_year}&position={positions}"
    file_path = Path(f'data/adp/adp_{adp_type}.json')
    try:
        with open(file_path, "r") as data_file:
            adp_data = json.load(data_file)
            adp_end_date = adp_data["meta"]["end_date"]
    except FileNotFoundError:
        adp_end_date = None
        pass

    if adp_end_date == TODAY:
        print(f"Loading local ADP data from {adp_end_date}")
    else:
        print(f"Local ADP data does not match today's date, {TODAY}. Making call to FFCalc.")
        try:
            response = requests.get(base_url)
            adp_data = response.json()
        except requests.exceptions.RequestException as e:
            if adp_end_date:
                print(f"Error {e} when making the remote call.  Using local data from {adp_end_date}")
                pass
            else:
                print("Error reading local copy and error reading remote copy.  Must break. ")
                pass
        finally:
            adp_dir = Path('data/adp')
            adp_dir.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w') as data_file:
                json.dump(adp_data, data_file, indent=4)

    with open(file_path, 'r') as file:
        adp_data = json.load(file)

    adp_dict = adp_data["players"]

    adp_df = pd.DataFrame(adp_dict)
    adp_df.rename(columns={"player_id": "ffcalc_id"}, inplace=True)
    adp_df["adp_pick"] = adp_df.index + 1
    adp_df = get_sleeper_ids(adp_df)

    end_time = time.time()
    print(f"Time to get ADP DF: {end_time - start_time}")

    return adp_df


def get_cheatsheet_list(df, pos):
    df = df[df["position"] == pos]  # ['position_tier_ecr', 'cheatsheet_text'].tolist()
    df = df[["position_tier_ecr", 'cheatsheet_text']]
    return df.values.tolist()


def get_db_arr(df, key, df_loc_col="is_keeper"):
    keys = {"adp": {"sort": "adp_pick", "pick_no": "adp_pick_no"},
            "ecr": {"sort": "superflex_rank_ecr", "pick_no": 'ecr_pick_no'},
            "keepers": {"sort": "", "pick_no": ""}
            }
    if key in ["adp", "ecr"]:
        sort = keys[key]['sort']
        pick_no = keys[key]['pick_no']
        non_kept_picks = [n + 1 for n in range(len(df)) if n + 1 not in df['pick_no'].to_list()]
        df[pick_no] = df["pick_no"]
        df.sort_values(by=sort, ascending=True, inplace=True)
        df.loc[df[df_loc_col] != True, f'{key}_pick_no'] = non_kept_picks
        df.sort_values(by=pick_no, ascending=True, inplace=True)
        arr = np.array(df[:MAX_ROWS * MAX_COLS].to_dict("records"))
        arr = np.reshape(arr, (MAX_ROWS, MAX_COLS))
        arr[1::2, :] = arr[1::2, ::-1]
    elif key == "keepers":
        arr = np.empty([MAX_ROWS, MAX_COLS])
        arr = np.reshape(arr, (MAX_ROWS, MAX_COLS))
        arr[1::2, :] = arr[1::2, ::-1]
        arr = np.full((MAX_ROWS, MAX_COLS), {"button_text": "\n\n", "position": "-", "sleeper_id": "-"})
        # Placing keepers on the empty draft board
        keeper_pool = df.loc[df["is_keeper"] == True].to_dict("records")
        for p in keeper_pool:
            loc = (p["round"] - 1, p["draft_slot"] - 1)
            arr[loc] = {"button_text": p["button_text"], "position": p["position"], "sleeper_id": p["sleeper_id"]}
    elif key == "live":
        arr = np.empty([MAX_ROWS, MAX_COLS])
        arr = np.reshape(arr, (MAX_ROWS, MAX_COLS))
        arr[1::2, :] = arr[1::2, ::-1]
        arr = np.full((MAX_ROWS, MAX_COLS), {"button_text": "\n\n", "position": "-", "sleeper_id": "-"})
        # Placing keepers on the empty draft board
        drafted_pool = df.loc[df["is_drafted"] == True].to_dict("records")
        for p in drafted_pool:
            loc = (p["round"] - 1, p["draft_slot"] - 1)
            arr[loc] = {"button_text": p["button_text"], "position": p["position"], "sleeper_id": p["sleeper_id"]}
        pass

    return arr


def DraftIdPopUp():
    sg.PopupScrolled('Select Draft ID')
    pass


def get_ecr_rankings(player_count=225):
    """
    Return single dataframe with columns for superflex_rank, suplerflex_tier,
    and pos_rank, pos_tier.  Also modify the self.dfs for projections.
    self.flex_df, self.rb_df, self.wr_df, self.te_df = self.clean_flex_df()
    """
    sf_rank_path = Path("data/fpros/FantasyPros_2022_Draft_SuperFlex_Rankings.csv")
    ecr_sf_df = pd.read_csv(sf_rank_path)
    ecr_sf_df.drop(columns="ECR VS. ADP", inplace=True)

    ecr_sf_df.rename(columns={"RK": "superflex_rank_ecr",
                              "TIERS": "superflex_tier_ecr",
                              "PLAYER NAME": "name",
                              "TEAM": "team",
                              "POS": "pos_rank",
                              "BYE WEEK": "bye",
                              "SOS SEASON": "sos_season"}, inplace=True)

    # do positional rankings now, combining them with single ECR DF
    # create dict to rename positional columns
    ecr_col_changes = {"RK": "position_rank_ecr", "TIERS": "position_tier_ecr", "PLAYER NAME": "name",
                       "TEAM": "team",
                       "POS": "position",
                       "BYE WEEK": "bye",
                       "SOS SEASON": "sos_season",
                       "ECR VS. ADP": "ecr_vs_adp"}

    ecr_qb_df = pd.read_csv("data/fpros/FantasyPros_2022_Draft_QB_Rankings.csv")
    ecr_rb_df = pd.read_csv("data/fpros/FantasyPros_2022_Draft_RB_Rankings.csv")
    ecr_wr_df = pd.read_csv("data/fpros/FantasyPros_2022_Draft_WR_Rankings.csv")
    ecr_te_df = pd.read_csv("data/fpros/FantasyPros_2022_Draft_TE_Rankings.csv")
    ecr_qb_df["position"] = "QB"
    ecr_rb_df["position"] = "RB"
    ecr_wr_df["position"] = "WR"
    ecr_te_df["position"] = "TE"
    ecr_df_list = [ecr_qb_df, ecr_rb_df, ecr_wr_df, ecr_te_df]
    for ecr_df in ecr_df_list:
        ecr_df.rename(columns=ecr_col_changes, inplace=True)
    pd.set_option("display.max_column", None)
    position_ecr_combined_df = pd.concat(ecr_df_list).fillna(0)
    cols_to_use = position_ecr_combined_df.columns.difference(ecr_sf_df.columns).to_list()
    cols_to_use.append("name")
    ecr_sf_df = pd.merge(ecr_sf_df.loc[:player_count], position_ecr_combined_df[cols_to_use], how="left", on="name")
    # pdb.set_trace()
    ecr_sf_df = get_sleeper_ids(ecr_sf_df)
    return ecr_sf_df


def clean_qb_df(qb_df):
    # lower case all column names
    qb_df.columns = qb_df.columns.str.lower()
    qb_df.dropna(inplace=True)
    qb_df.rename(columns={"tds": "pass_td",
                          "ints": "pass_int",
                          "att": "pass_att",
                          "att.1": "rush_att",
                          "yds": "pass_yd",
                          "yds.1": "rush_yd",
                          "tds.1": "rush_td",
                          "fl": "fum_lost",
                          "player": "name"}, inplace=True)
    qb_df["position_rank_projections"] = qb_df.index + 1
    qb_df["position_rank_projections"].fillna(0, inplace=True)
    # remove non-numeric (commas) characters from the number fields
    print(qb_df[pd.to_numeric(qb_df.pass_yd, errors='coerce').isnull()])
    # qb_df.apply(lambda x: x.str.replace(',', '.'))  # replace(',', '', regex=True, inplace=True)
    # df.apply(lambda ))
    qb_df["pass_yd"] = qb_df["pass_yd"].apply(pd.to_numeric, errors='coerce')
    qb_df["position"] = "QB"
    qb_df["pos_rank"] = qb_df["position"] + qb_df["position_rank_projections"].astype(str)



    return qb_df


def clean_flex_df(flex_df):
    """
    Take the single Flex CSV, clean up the column names, add the position and bonus
    columns,END.       XXX get custom score, split into positional DataFrames, and add VBD XXXX
    """

    flex_df.columns = flex_df.columns.str.lower()
    flex_df["position"] = flex_df["pos"].str[:2]
    flex_df["position_rank_projections"] = flex_df["pos"].str[2:]
    flex_df["position_rank_projections"].fillna(0, inplace=True)
    flex_df["position_rank_projections"] = pd.to_numeric(flex_df["position_rank_projections"], errors="coerce", downcast='integer')
    flex_df["bonus_rec_te"] = flex_df["rec"].loc[flex_df["position"] == "TE"]
    flex_df["bonus_rec_te"] = flex_df['bonus_rec_te'].fillna(0)
    flex_df.rename(columns={"player": "name",
                            "pos": "pos_rank",
                            "att": "rush_att",
                            "tds": "rush_td",
                            "yds": "rush_yd",
                            "yds.1": "rec_yd",
                            "tds.1": "rec_td",
                            "team": "team",
                            "fpts": "fpts",
                            "rec": "rec",
                            "fl": "fum_lost"}, inplace=True)

    # remove non numeric characters from the number fields
    flex_df.replace(',', '', regex=True, inplace=True)
    flex_df["rec_yd"] = flex_df["rec_yd"].apply(pd.to_numeric)
    flex_df["rush_yd"] = flex_df["rush_yd"].apply(pd.to_numeric)

    # calculate custom score and sort
    # flex_df["fpts"] = flex_df.apply(self.get_custom_score_row, axis=1)
    # flex_df.sort_values(by="fpts", inplace=True, ascending=False)

    flex_df.dropna(inplace=True, thresh=5)

    return flex_df


def get_cheatsheet_data(df, pos="all", hide_drafted=False):
    """
    Cheat Sheet Data for the rows of the tables building
    """
    import warnings

    pos = pos.upper()  # Make pos var CAPS to align with position values "QB, RB, WR TE" and sg element naming format
    # ------ Remove Kickers and Defenses ------- #
    df = df.loc[df["position"].isin(["QB", "RB", "WR", "TE"])]

    if hide_drafted:
        df = df.loc[df["is_keeper"].isin([False, None]), :]
        df = df.loc[df["is_drafted"].isin([False, None]), :]
    else:
        pass

    if pos == "ALL":
        df = df.sort_values(by=['superflex_rank_ecr'], ascending=True, na_position='last')
        cols = ['sleeper_id', 'superflex_tier_ecr', 'cheatsheet_text']
    elif pos == "BOTTOM":
        df = df.sort_values(by=["vbd_rank"], ascending=True, na_position="last")
        cols = ['sleeper_id', 'name', 'fpts', 'vbd_rank', 'position_rank_vbd', 'vbd', 'vorp', 'vols', 'vona']
    else:
        df = df.loc[df.position == pos]
        cols = ['sleeper_id', 'position_tier_ecr', 'cheatsheet_text']
        df = df.sort_values(by=["position_rank_ecr"], ascending=True, na_position="last")

    df = df[cols]
    # df = df.fillna(value="999")
    table_data = df.values.tolist()
    return table_data


def get_bottom_table(df, hide_drafted=False):
    if hide_drafted:
        df = df.loc[df["is_drafted"].isin([False, None]), :]
    else:
        pass

    df = df.sort_values(by=["vbd_rank"], ascending=True, na_position="last")

    cols = ['sleeper_id', 'name', 'fpts', 'vbd_rank', 'position_rank_vbd', 'vbd', 'vorp', 'vols', 'vona']
    df = df[cols]
    df = df.fillna({'fpts': 0,
                    'vbd_rank': 0,
                    'position_rank_projections': 0,
                    'position_rank_vbd': 0,
                    'vbd': 0,
                    'vorp': 0,
                    'vols': 0,
                    'vona': 0})
    table_data = df.values.tolist()
    headings_list = ['sleeper_id', 'Name', 'fpts', 'VBD Rank', 'VBD Pos Rank', 'VBD', 'VORP', 'VOLS', 'VONA']
    table = sg.Table(table_data, headings=headings_list,
                     # col_widths=[0, 3, 20],
                     visible_column_map=[False, True, True, True, True, True, True, True, True],
                     auto_size_columns=True,
                     max_col_width=20,
                     sbar_width=2,
                     display_row_numbers=False,
                     vertical_scroll_only=False,
                     num_rows=min(50, len(table_data)), row_height=15, justification="left",
                     key=f"-BOTTOM-TABLE-", expand_x=True, expand_y=True, visible=True)
    return table


def get_cheatsheet_table(df, pos="all", hide_drafted=False):
    table_data = get_cheatsheet_data(df, pos, hide_drafted)
    table = sg.Table(table_data, headings=['sleeper_id', 'Tier', pos, ],
                     col_widths=[0, 3, 20],
                     visible_column_map=[False, True, True],
                     auto_size_columns=False,
                     max_col_width=20,
                     sbar_width=2,
                     display_row_numbers=False,
                     num_rows=min(10, len(table_data)), row_height=15, justification="left",
                     key=f"-{pos}-TABLE-", expand_x=True, expand_y=True, visible=True)
    return table


def get_draft_order(league):
    """
      Get League and user/map
      """

    user_map = league.map_users_to_team_name()
    """
    Get all picks in sleeper draft
    """
    league_dict = league.get_league()
    draft_id = league_dict["draft_id"]
    # DRAFT_IDs
    # = 859302163317399552  # 850087629952249857  # 858793089177886720  # 855693188285992960  # mock 858792885288538112
    # DRAFT_ID_2022_WEEZ_LEAGUE = 850087629952249857  # 854953046042583040

    """
    get draft order from weez league, map to the user names, and sort by the draft position
    """
    draft = Drafts(draft_id)
    draft_info = draft.get_specific_draft()

    try:
        draft_order = draft_info['draft_order']
        draft_order = {v: user_map[k] for k, v in draft_order.items()}
    except:
        draft_order = [x for x in range(MAX_COLS)]

    return draft_order



def get_fpros_projections():
    # qb_path = Path("../sleeper-api-wrapper/data/fpros/FantasyPros_Fantasy_Football_Projections_QB.csv")
    # flex_path = Path("../sleeper-api-wrapper/data/fpros/FantasyPros_Fantasy_Football_Projections_FLX.csv")
    qb_path = Path("data/fpros/FantasyPros_Fantasy_Football_Projections_QB.csv")
    flex_path = Path("data/fpros/FantasyPros_Fantasy_Football_Projections_FLX.csv")
    qb_df = pd.read_csv(qb_path, skiprows=[1], thousands=",")
    flex_df = pd.read_csv(flex_path, skiprows=[1], thousands=",")

    qb_df = clean_qb_df(qb_df)
    qb_df = get_sleeper_ids(qb_df)
    flex_df = clean_flex_df(flex_df)
    flex_df = get_sleeper_ids(flex_df)

    prj_df = pd.concat([qb_df, flex_df]).fillna(0)

    return prj_df


def get_fpros_data(player_count=225):
    ecr_df = get_ecr_rankings(player_count)
    prj_df = get_fpros_projections()
    fpros_df = merge_dfs(ecr_df, prj_df, "sleeper_id")
    fpros_df.fillna({'fpts': 0, 'bonus_rec_te': 0}, inplace=True)
    return fpros_df


def merge_dfs(df1, df2, col_to_match, how="left"):
    cols_to_use = df2.columns.difference(df1.columns).to_list()
    cols_to_use.append(col_to_match)
    df = pd.merge(df1, df2[cols_to_use], how=how, on=col_to_match)
    return df


def get_player_pool(player_count=400, adp_type='2qb'):
    start_time = time.time()
    fpros_df = get_fpros_data(player_count)
    adp_df = get_adp_df(adp_type=adp_type)

    # remove kickers and defenses
    adp_kd = adp_df.loc[adp_df['position'].isin(["PK", "DEF"])]

    # Fix Defensive Names
    adp_kd.loc[adp_kd["position"] == "DEF", "last_name"] = adp_kd.name.str.split(' ').str[-1]
    adp_kd.loc[adp_kd["position"] == "DEF", "first_name"] = adp_kd.name.str.replace(' Defense', '')

    # Get ADP DF of only position groups
    adp_df = adp_df.loc[adp_df['position'].isin(["QB", "WR", "TE", "RB"])]
    # merge adp w/out K and D to the fpros dataframe
    p_pool = merge_dfs(fpros_df, adp_df, "sleeper_id", how="outer")
    # Now merge kickers and defenses back in
    p_pool = pd.concat([p_pool, adp_kd])

    # Now time to clean up some ranking columns
    p_pool.sort_values(by=['adp_pick', 'superflex_rank_ecr'], na_position='last', inplace=True)
    p_pool.reset_index(drop=True, inplace=True)
    p_pool['adp_pick'] = p_pool.index + 1

    # ----Clean up columns to be INT values and fill NA ------ #
    cols = ['superflex_rank_ecr', 'superflex_tier_ecr', 'position_rank_ecr', 'position_tier_ecr']
    p_pool[cols] = p_pool[cols].fillna(value=999).astype(int)
    for col in cols:
        p_pool[col] = pd.to_numeric(p_pool[col], errors="coerce", downcast='integer')
    p_pool['team'] = p_pool['team'].fillna("FA")
    p_pool['pos_rank'] = p_pool["pos_rank"].fillna("NA999")

    # Now time to add the button_text and cheatsheet_text values
    p_pool["cheatsheet_text"] = p_pool['pos_rank'] + ' ' + p_pool['name'] + ' ' + p_pool['team']
    p_pool["button_text"] = p_pool['first_name'] + '\n' + p_pool['last_name'] + '\n' + p_pool[
        'position'] + ' (' + p_pool['team'] + ') ' + p_pool['bye'].astype(str)

    # Add in None values for Keeper columns
    # board_loc will eventually be the tuple that can be used to place on the draftboard array
    k_cols = ['is_keeper', 'is_drafted', 'pick_no', 'draft_slot', 'round', 'board_loc']

    for k in k_cols:
        p_pool[k] = None

    # Open keeper list of dicts so that we can set the keeper value to True
    keeper_list = open_keepers(get="list")

    # iterate over the keeper list to grab the dict values and assign to the main player_pool dataframe
    for player_dict in keeper_list:
        p = player_dict
        if 'player_id' in p.keys():
            p['sleeper_id'] = p['player_id']
        id = p['sleeper_id']
        is_keeper = p['is_keeper']
        # initializing the keeper/drafted value as them same.  The values will update while drafting
        is_drafted = False  # p['is_keeper']
        pick_no = p['pick_no']
        slot = p['draft_slot']
        rd = p['round']
        board_loc = "hi"
        try:
            p_pool.loc[p_pool['sleeper_id'] == id, k_cols] = [is_keeper, is_drafted, pick_no, slot, rd, board_loc]
        except:
            print(board_loc)
            pdb.set_trace()
    # now add the adp_k_pick column
    # p_pool.sort_values(by=['adp_pick'], ascending=True, inplace=True)

    p_pool.dropna(subset=["name", "button_text"], inplace=True)

    # ------Now Detect if league exists and then calc custom score. -----#
    p_pool, draft_order, league_found = load_saved_league(p_pool)
    # ---- Add VBD per position  ----- #
    p_pool = add_vbd(p_pool)

    end_time = time.time()
    print(f"Time to make Player Draft Pool: {end_time - start_time}")
    return p_pool, draft_order, league_found


def load_saved_league(df):

    """
    Reading the last used League ID to bring in league settings.
    draft_order used to set the buttons for the board columns/teams.
    The league info should change if a new league is loaded.
    """
    league_id_json = Path('data/league_ids/leagues.json')
    try:
        with open(league_id_json, "r") as file:
            league_id_list = json.load(file)
            league_id_list = list(set(league_id_list))
            # ----Get Text for Draft Order Buttons (teams) ------#
            league = League(league_id_list[0])
            draft_order = get_draft_order(league)
            # ---Calc Custom Scores-------#
            start_time = time.time()
            sg.popup_quick_message("Calculating Custom Score")
            df['fpts'] = df.apply(lambda row: get_custom_score_row(row, league.scoring_settings), axis=1)
            df['fpts'].fillna(0)
            league_found = True
            end_time = time.time()
            print(f"Time to calc custom scores: {end_time-start_time}")
    except FileNotFoundError:
        sg.popup_quick_message("League not found.")
        league_found = False
        Path('data/league_ids').mkdir(parents=True, exist_ok=True)
        league_id_list = []
        draft_order = [x for x in range(MAX_COLS + 1)]

    return df, draft_order, league_found


def reorder_keepers(key, p_pool):
    p_pool.sort_values(by=[key], ascending=True, inplace=True)
    return


def open_keepers(get=None):
    keeper_json_path = Path('data/keepers/keepers.json')
    try:
        with open(keeper_json_path, "r") as data:
            keeper_list = json.load(data)
            print(f"Total Keepers Found: {len(keeper_list)}")
            keeper_list_text = [f"{k['round']}.{k['draft_slot']}" for k in keeper_list]
            # keeper_list_text = [f"{k['name']} {k['round']}.{k['draft_slot']}" for k in keeper_list]
    except KeyError:
        with open(keeper_json_path, "r") as data:
            keeper_list = json.load(data)
            print(f"Opened Keeper List: {keeper_list}")
            keeper_list_text = [f"{k['round']}.{k['draft_slot']}" for k in keeper_list]
            # keeper_list_text = [f"{k['name']} {k['round']}.{k['draft_slot']}" for k in keeper_list]
    except FileNotFoundError:
        keeper_list = []
        keeper_list_text = []

    if not get:
        return keeper_list, keeper_list_text
    elif get == "list":
        return keeper_list
    elif get == "text":
        return keeper_list_text
    else:
        print("Can only accept 'list' or 'text'")
        return None


def clear_all_keepers():
    keeper_list = []
    Path('data/keepers').mkdir(exist_ok=True, parents=True)
    with open('data/keepers/keepers.json', 'w') as file:
        json.dump(keeper_list, file, indent=4)
    print("keepers.json overwritten, set as []")

"""
Custom score and VBD info ported from fpros]
"""


def get_custom_score_row(row, scoring_keys):
    score = 0
    for k, v in scoring_keys.items():
        try:
            score += scoring_keys[k] * row[k]
        except KeyError:
            pass
    return round(score, 2)


def add_vbd(df):

    # or pos in ["QB", "RB", "WR", "TE"]:
    #     p_pool.loc[p_pool["position"] == pos] = add_vbd(p_pool, pos)
    # get thresholds
    df = sort_reset_index(df, sort_by="fpts")

    vols_cutoff = {"QB": 25, "RB": 25, "WR": 25, "TE": 10}
    vorp_cutoff = {"QB": 31, "RB": 55, "WR": 63, "TE": 22}
    new_df = pd.DataFrame()
    for pos in ["QB", "RB", "WR", "TE"]:
        temp_df = df.loc[df["position"] == pos]
        vols_threshold = temp_df.iloc[vols_cutoff[pos]]
        vorp_threshold = temp_df.iloc[vorp_cutoff[pos]]

        # TODO Figure out this chained_assignment issue with the error message of:
        #       SettingWithCopyError:
        #       A value is trying to be set on a copy of a slice from a DataFrame.
        #       Try using .loc[row_indexer,col_indexer] = value instead
        pd.options.mode.chained_assignment = None
        temp_df["vols"] = temp_df.apply(lambda row: calc_vols(row, vols_threshold), axis=1)
        temp_df["vorp"] = temp_df.apply(lambda row: calc_vorp(row, vorp_threshold), axis=1)
        temp_df["vbd"] = temp_df.apply(lambda row: calc_vbd(row), axis=1)
        temp_df['vona'] = round(temp_df.fpts.diff(periods=-1))
        temp_df = sort_reset_index(temp_df, sort_by=["vbd", "fpts"])
        temp_df["position_rank_vbd"] = temp_df.index + 1
        new_df = pd.concat([new_df, temp_df], axis=0)
        # print(new_df)

    new_df = merge_dfs(new_df, df, "sleeper_id", how="outer")
    new_df = sort_reset_index(new_df, sort_by=["vbd", "fpts"])
    new_df['vbd_rank'] = new_df.index + 1
    name1 = df["name"].tolist()
    name2 = new_df["name"].tolist()
    names_not_in = list(set(name2) - set(name1))
    print(names_not_in)

    return new_df



def sort_reset_index(df, sort_by):
    """
    This gets called every time we add vbd to sort by vbd and reset the index
    """
    df.sort_values(by=sort_by, ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def calc_vols(row, vols_threshold):
    return int(max(0, row['fpts'] - vols_threshold['fpts']))


def calc_vorp(row, vorp_threshold):
    return int(max(0, row['fpts'] - vorp_threshold['fpts']))


def calc_vbd(row):
    return int(max(0, row['vols'] + row['vorp']))


