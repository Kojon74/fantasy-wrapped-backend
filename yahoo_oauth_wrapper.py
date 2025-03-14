from yahoo_oauth.oauth import BaseOAuth
from dotenv import load_dotenv
import os
from rauth import OAuth2Service

load_dotenv()
CLIENT_ID = os.getenv("YAHOO_CONSUMER_KEY")
CLIENT_SECRET = os.getenv("YAHOO_CONSUMER_SECRET")

oauth_service = {
    "SERVICE": OAuth2Service,
    "AUTHORIZE_TOKEN_URL": "https://api.login.yahoo.com/oauth2/request_auth",
    "ACCESS_TOKEN_URL": "https://api.login.yahoo.com/oauth2/get_token",
}

CALLBACK_URI = "oob"

STORE_FILE_FLAG = True

BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"


class YahooOAuthWrapper(BaseOAuth):
    def __init__(self, access_token, refresh_token):
        self.consumer_key = CLIENT_ID
        self.consumer_secret = CLIENT_SECRET
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.oauth_version = "oauth2"
        self.callback_uri = CALLBACK_URI
        self.store_file = STORE_FILE_FLAG
        service_params = {
            "client_id": self.consumer_key,
            "client_secret": self.consumer_secret,
            "name": "yahoo",
            "access_token_url": oauth_service["ACCESS_TOKEN_URL"],
            "authorize_url": oauth_service["AUTHORIZE_TOKEN_URL"],
            "base_url": BASE_URL,
        }

        # Defining oauth service
        self.oauth = oauth_service["SERVICE"](**service_params)

        # Getting session
        self.session = self.oauth.get_session(token=self.access_token)
