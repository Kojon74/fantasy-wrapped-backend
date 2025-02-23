import os
from yahoo_oauth import OAuth2
import requests
from requests.adapters import HTTPAdapter, Retry
from utils import xml_to_dict
from yahoo_oauth_wrapper import YahooOAuthWrapper

BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"

class Query():
    def __init__(self, token, league_key):
        self.oauth = self.authenticate(token)
        
        self.oauth.refresh_access_token() # In case access_token is already expired
        self.session = self.init_session()
        self.league_key = league_key
        self.game_id, _, self.league_id = league_key.split(".")


    def authenticate(self, token):
        return YahooOAuthWrapper(token["access_token"], token["refresh_token"])

    def init_session(self):
        session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=0.1,
            status_forcelist=[ 500, 502, 503, 504 ]
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def get_response(self, url):
        if not self.oauth.token_is_valid():
            self.oauth.refresh_access_token()

        headers = {
            "Authorization": f"Bearer {self.oauth.access_token}",
            "Content-Type": "application/json"
        }
        response = self.session.get(url, headers=headers)
        if response.status_code != 200:
            print(response)
            print(response.text)
            response.raise_for_status()
        xml = response.text
        data = xml_to_dict(response.text)
        return data

    def get_teams(self):
        """
        Returns:
        {[team_key: string]: {team_image: string, team_name: string, team_nickname: string}}
        """
        url = f"{BASE_URL}/league/{self.league_key};out=standings"
        teams = self.get_response(url)["league"]["standings"]["teams"]
        teams_dict = {team["team_key"]: {"image": team["managers"]["manager"]["image_url"], "name": team["name"], "nickname": team["managers"]["manager"]["nickname"]} for team in teams}
        standings = [{"key": team["team_key"], "value": i+1} for i, team in enumerate(teams)] # More efficient to combine two loops?
        return teams_dict, standings