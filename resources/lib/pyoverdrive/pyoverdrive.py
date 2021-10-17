# Copyright (C) 2021 Raymond Olsen
#
# This file is part of pyoverdrive.
#
# pyoverdrive is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyoverdrive is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyoverdrive. If not, see <http://www.gnu.org/licenses/>.

import json
import requests
from http import cookiejar
import os
import base64
import uuid
import xmltodict
import datetime
import hashlib


class Overdrive:
    login_url = "/account/signInOzone?forwardUrl=%2F"
    sign_in_url = "/account/ozone/sign-in?forward=%2F&showIdcSignUp=false"
    account_url = "/rest/account/"
    info_url = "/media/info/"
    loans_url = "/account/loans"
    download_url = "/media/download/audiobook-mp3/"
    user_agent = "OverDrive Media Console"
    client_id = str(uuid.uuid1()).upper()
    OMC = "1.2.0"
    OS = "10.11.6"

    def __init__(self, url, card_number=None, password=None, cookiejar_path=None, lic_path="lic/",
                 download_path="downloads/", login=True):
        self.card_number = card_number
        self.password = password
        self.base_url = url
        self.lic_path = lic_path
        self.download_path = download_path

        if cookiejar_path is None:
            cookiejar_path = "cookiejar"

        self.cj = cookiejar.LWPCookieJar(cookiejar_path)
        if not os.path.isfile(cookiejar_path):
            self.cj.save()
        else:
            self.cj.load()

        self.http_session = requests.Session()
        self.http_session.cookies = self.cj

        if login:
            # Check if we are logged in
            account = self.get_account()
            if "sessionExpired" in account and account["sessionExpired"]:
                print("Session is expired, logging in")
                self.login()

                # Check if we are logged in now
                account = self.get_account()
                if "lastHoldEmail" in account or "email" in account:
                    print("Successfully logged in!")
                    return
                else:
                    print("Couldn't log in. Please check your credentials and library url.")
                    raise SystemExit(1)
            elif "lastHoldEmail" in account or "email" in account:
                print("Cookies still valid, we are logged in")
            else:
                print("Couldn't log in. Please check library url and try again.")
                raise SystemExit(1)

    def get_ils_name(self):
        resp = self.http_session.get(self.create_url(self.sign_in_url)).content
        login_line = [line for line in resp.decode("utf-8").split('\n') if "window.OverDrive.loginForms = " in line][0]
        login_line = login_line.replace("window.OverDrive.loginForms =", "").strip()[:-1]
        login = json.loads(login_line)
        return login["forms"][0]["ilsName"]

    def login(self):
        print(f"Logging in to {self.base_url}")
        payload = {
           "ilsName": self.get_ils_name(),
           "authType": "Local",
           "libraryName": "",
           "username": self.card_number
        }

        if self.password:
            payload["password"] = self.password

        self.http_session.post(self.create_url(self.login_url), data=payload)

    def get_account(self):
        resp = self.http_session.get(self.create_url(self.account_url)).content
        return json.loads(resp)

    def get_loans(self):
        print("Getting loans")
        resp = self.http_session.get(self.create_url(self.loans_url)).content
        media_line = [line for line in resp.decode("utf-8").split('\n') if "window.OverDrive.mediaItems = " in line][0]
        media_line = media_line.replace("window.OverDrive.mediaItems =", "").strip()[:-1]
        media = json.loads(media_line)
        return media

    def get_odm(self, media_id):
        print("Getting odm")
        download_path = self.lic_path + str(media_id) + ".odm"

        # Check if we already have the odm
        if os.path.isfile(download_path):
            should_download_again = False

            # If it has expired, download it again
            with open(download_path, "r") as r:
                odm = r.read()
                odm_dict = xmltodict.parse(odm)

            expiry_iso_string = odm_dict["OverDriveMedia"]["DrmInfo"]["ExpirationDate"]
            expiry = datetime.datetime.fromisoformat(expiry_iso_string[:-1])

            # If odm is downloaded, but also expired (WILL DELETE!)
            if datetime.datetime.now() > expiry:
                print("Expired! Deleting!!!")
                os.remove(download_path)
                if os.path.isfile(str(media_id) + ".lic"):
                    os.remove(str(media_id) + ".lic")
                should_download_again = True

            if not should_download_again:
                print("We already have the odm and it has not expired.")
                return xmltodict.parse(odm)

        # Check if we have a loan on the media_id
        loans = self.get_loans()
        if str(media_id) not in loans:
            print(f"You do not have a loan on media with id {media_id}, or you are not logged in.")
            return

        print("Downloading odm")
        resp = self.http_session.get(self.create_url(self.download_url) + str(media_id)).content
        with open(download_path, "wb") as w:
            w.write(resp)

        return xmltodict.parse(resp.decode("utf-8"))

    def get_license(self, media_id):
        print("Getting license")
        lic_path = self.lic_path + str(media_id) + ".lic"
        odm = self.get_odm(media_id)
        if not odm:
            print("Couldn't get license because couldn't get odm")
            return

        if os.path.isfile(lic_path):
            print("Already have the license")
            with open(lic_path, "r") as r:
                lic = xmltodict.parse(r.read())
                lic["odm"] = odm
                return lic

        # Thanks to
        # https://github.com/ping/odmpy,
        # https://github.com/chbrown/overdrive
        # and https://github.com/jvolkening/gloc
        raw_hash = f"{self.client_id}|{self.OMC}|{self.OS}|ELOSNOC*AIDEM*EVIRDREVO"
        m = hashlib.sha1(raw_hash.encode("utf-16-le"))
        license_hash = base64.b64encode(m.digest())

        # Download license file
        params = {
            "MediaID": odm["OverDriveMedia"]["@id"],
            "ClientID": self.client_id,
            "OMC": self.OMC,
            "OS": self.OS,
            "Hash": license_hash
        }

        resp = self.http_session.get(
            odm["OverDriveMedia"]["License"]["AcquisitionUrl"],
            params=params,
            headers={"User-Agent": self.user_agent},
            timeout=10
        )

        if resp.status_code in [404, 400]:
            try:
                print(xmltodict.parse(resp.content.decode("utf-8"))["LicenseError"]["ErrorCode"],
                    xmltodict.parse(resp.content.decode("utf-8"))["LicenseError"]["ErrorMessage"])
            except:
                print("Couldn't get license.")
            return

        with open(lic_path, "wb") as w:
            w.write(resp.content)

        lic = xmltodict.parse(resp.content)
        lic["odm"] = odm
        return lic

    def get_metadata(self, media_id):
        odm = self.get_odm(media_id)
        return xmltodict.parse(odm["OverDriveMedia"]["#text"])

    def get_author(self, media_id):
        metadata = self.get_metadata(media_id)
        return [a["#text"] for a in metadata["Metadata"]["Creators"]["Creator"] if a["@role"] == "Author"][0]

    def get_title(self, media_id):
        return self.get_metadata(media_id)["Metadata"]["Title"]

    def get_part_info(self, media_id):
        odm = self.get_odm(media_id)
        return odm["OverDriveMedia"]["Formats"]["Format"]["Parts"]

    def download_book(self, media_id: int, part: int = None, download: bool = True):
        """
        Download a book or a part of a book. If download=False return urls and header info instead.

        :param media_id: media_id to download
        :param part: part to download. None=All parts
        :param download: To download or return urls + headers.
        :return: If download is True, nothing, else a dict with urls and headers.
        """

        lic = self.get_license(media_id)
        if not lic:
            print("Could not download book because couldn't get license.")
            return

        if not os.path.isfile((self.lic_path + str(media_id) + ".lic")):
            print("License file does not exist, not downloading book")
            return

        with open(self.lic_path + str(media_id) + ".lic", "r") as r:
            lic_file_contents = r.read()

        base_url = lic["odm"]["OverDriveMedia"]["Formats"]["Format"]["Protocols"]["Protocol"]["@baseurl"]
        urls = None
        if not part:
            urls = [{"url": base_url + "/" + f["@filename"],
                     "part": f["@name"]} for f in lic["odm"]["OverDriveMedia"]["Formats"]["Format"]["Parts"]["Part"]]
        else:
            for p in lic["odm"]["OverDriveMedia"]["Formats"]["Format"]["Parts"]["Part"]:
                if p["@number"] == str(part):
                    urls = [{"url": base_url + "/" + p["@filename"], "part": p["@name"]}]
                    break

        if not urls:
            print("Couldn't find url for part(s)")
            return

        headers = {
            "User-Agent": self.user_agent,
            "ClientID": lic["License"]["SignedInfo"]["ClientID"],
            "License": lic_file_contents,
        }

        if not download:
            return {"urls": urls, "headers": headers}

        author = self.get_author(media_id)
        title = self.get_title(media_id)

        if not os.path.isdir(self.download_path + author):
            os.mkdir(self.download_path + author)
        if not os.path.isdir(self.download_path + author + "/" + title):
            os.mkdir(self.download_path + author + "/" + title)

        path = self.download_path + author + "/" + title + "/"

        for u in urls:
            resp = self.http_session.get(
               u["url"],
               headers=headers,
               timeout=10,
               stream=True)

            try:
                resp.raise_for_status()
                with open(path + f"{author} - {title} {u['part']}", "wb") as outfile:
                    downloaded = 0
                    mb = 0
                    for chunk in resp.iter_content(1024):
                        outfile.write(chunk)
                        downloaded += 1024
                        if downloaded > 1024*1000:
                            mb += 1
                            downloaded = 0
                            print(f"Downloaded {mb}MB")
                print(f"Downloaded {author} - {title} {u['part']}")

            except Exception as e:
                print("Exception!")
                print(str(e))
                return

    def create_url(self, url):
        return self.base_url + url


if __name__ == "__main__":
    pass
