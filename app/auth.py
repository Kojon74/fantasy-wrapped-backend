import os
from yahoo_oauth import OAuth2
from dotenv import load_dotenv

from yahoo_oauth_wrapper import YahooOAuthWrapper

load_dotenv()
CLIENT_ID = os.getenv("YAHOO_CONSUMER_KEY")
CLIENT_SECRET = os.getenv("YAHOO_CONSUMER_SECRET")


def authenticate(token):
    if not token:
        return OAuth2(CLIENT_ID, CLIENT_SECRET, browser_callback=True)
    return YahooOAuthWrapper(token["access_token"], token["refresh_token"])
