# Copyright (C) 2021 Raymond Olsen
#
# This file is part of plugin.audio.overdrive.
#
# plugin.audio.overdrive is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# plugin.audio.overdrive is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with plugin.audio.overdrive. If not, see <http://www.gnu.org/licenses/>.

import routing
from xbmcgui import ListItem
from xbmcplugin import addDirectoryItem, endOfDirectory, addSortMethod
from resources.lib.pyoverdrive.pyoverdrive import Overdrive
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
import os
import xbmcplugin
import urllib.parse
import json
from threading import Thread

__addon__ = xbmcaddon.Addon()
__addondir__ = __addon__.getAddonInfo('profile')
data_folder = xbmcvfs.translatePath(__addondir__)

plugin = routing.Plugin()
xbmcplugin.setContent(plugin.handle, 'albums')

if not os.path.isdir(data_folder):
    os.mkdir(data_folder)
if not os.path.isdir(data_folder+"lic/"):
    os.mkdir(data_folder+"lic/")

libraries = []
libraries_path = data_folder+"libraries.json"


def save_libraries():
    with open(libraries_path, "w") as w:
        w.write(json.dumps(libraries, indent=4))
    xbmc.log("Libraries saved", xbmc.LOGINFO)


def load_libraries():
    global libraries
    if not os.path.isfile(libraries_path):
        with open(libraries_path, "w") as w:
            w.write(json.dumps([]))
    else:
        with open(libraries_path, "r") as r:
            libraries = json.loads(r.read())
    xbmc.log("Libraries loaded", xbmc.LOGINFO)


ods = {}
load_libraries()


# Tried to speed it up a bit.
# Multithreaded = 1.5sec for 3 libs vs singlethreaded 4secs.
def init_overdrive(url=None):
    if not url:
        thread_list = []

        def init_ods(l):
            od = Overdrive(l["url"], l["username"], l["password"],
                           cookiejar_path=data_folder + "cookiejar", lic_path=data_folder+"lic/")
            ods[l["url"]] = od
            xbmc.log(f"Added {l['url']} to overdrives", xbmc.LOGINFO)

        for lib in libraries:
            t = Thread(target=init_ods, args=(lib,))
            t.start()
            xbmc.log(f"Starting thread", xbmc.LOGDEBUG)
            thread_list.append(t)

        for thread in thread_list:
            thread.join()
        xbmc.log(f"Threads done", xbmc.LOGDEBUG)
        return

    for l in libraries:
        if url == l["url"]:
            od = Overdrive(l["url"], l["username"], l["password"],
                           cookiejar_path=data_folder + "cookiejar", lic_path=data_folder+"lic/")
            ods[l["url"]] = od
            xbmc.log(f"Added {l['url']} to overdrives", xbmc.LOGINFO)
            return


@plugin.route('/')
def index():
    init_overdrive()
    thread_list = []

    def get_loans(od):
        loans = ods[od].get_loans()
        for l in loans:
            li = ListItem(f"{loans[l]['firstCreatorName']}: {loans[l]['title']}")
            art = {
                "thumb": loans[l]["covers"]["cover510Wide"]["href"],
                "icon": loans[l]["covers"]["cover510Wide"]["href"],
            }

            info = {
                "genre": ", ".join([g["name"] for g in loans[l]["subjects"]]),
                "title": loans[l]['title'],
                "artist": loans[l]['firstCreatorName'],
                # "plot": od.get_metadata(l)["Metadata"]["Description"].replace("<p>", "")
            }

            li.setArt(art)
            li.setInfo("music", info)
            addDirectoryItem(plugin.handle, plugin.url_for(show_book, urllib.parse.quote_plus(od), l), li, True)

    for od in ods:
        t = Thread(target=get_loans, args=(od,))
        t.start()
        thread_list.append(t)

    li = ListItem("Add/Remove Libraries")
    li.setProperty("SpecialSort", "bottom")
    addDirectoryItem(plugin.handle, plugin.url_for(edit_libraries), li, True)

    #addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_TITLE, '...')
    addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_ARTIST)

    # Make sure we are done with getting the books
    for thread in thread_list:
        thread.join()

    # We don't want to cache this in case user borrows/returns books. They should appear at once.
    endOfDirectory(plugin.handle, cacheToDisc=False)


def get_overdrive(library_url):
    xbmc.log(f"Getting Overdrive for url: {urllib.parse.unquote_plus(library_url)}", xbmc.LOGINFO)
    try:
        overdrive = [ods[od] for od in ods if od == urllib.parse.unquote_plus(library_url)][0]
        xbmc.log("We already had the overdrive, loaded it from ods", xbmc.LOGDEBUG)
        return overdrive
    except IndexError:
        xbmc.log("We didn't have the overdrive, inited it", xbmc.LOGDEBUG)
        init_overdrive(urllib.parse.unquote_plus(library_url))
    finally:
        return [ods[od] for od in ods if od == urllib.parse.unquote_plus(library_url)][0]


@plugin.route('/library/<library_url>/media_id/<media_id>')
def show_book(library_url, media_id):
    part_info = get_overdrive(library_url).get_part_info(media_id)
    for p in part_info["Part"]:
        li = ListItem(p["@name"])
        info = {
            "duration": int(p["@duration"].split(":")[0])*60 + int(p["@duration"].split(":")[1]),
        }
        li.setInfo("music", info)
        li.setProperty('IsPlayable', 'true')

        url_info = get_overdrive(library_url).download_book(media_id, p["@number"], download=False)
        headers = url_info["headers"]
        header_string = f"User-Agent={urllib.parse.quote_plus(headers['User-Agent'])}" \
                        f"&ClientID={urllib.parse.quote_plus(headers['ClientID'])}" \
                        f"&License={urllib.parse.quote_plus(headers['License'])}"

        li.setPath(url_info["urls"][0]["url"])
        addDirectoryItem(plugin.handle, url_info["urls"][0]["url"] + "|" + header_string, li, isFolder=False)

    endOfDirectory(plugin.handle)


@plugin.route('/edit_libraries')
def edit_libraries():
    for l in libraries:
        li = ListItem(f"Remove {l['url']}")
        addDirectoryItem(plugin.handle, plugin.url_for(remove_library, urllib.parse.quote_plus(l["url"])), li, isFolder=False)

    li = ListItem("Add Library")
    addDirectoryItem(plugin.handle, plugin.url_for(add_library), li, isFolder=False)
    endOfDirectory(plugin.handle)


@plugin.route('/remove_library/<library_url>')
def remove_library(library_url):
    global libraries
    libraries = [l for l in libraries if l["url"] != urllib.parse.unquote_plus(library_url)]
    save_libraries()
    xbmcgui.Dialog().ok("Overdrive", f"Removed {library_url}")
    xbmc.executebuiltin('Container.Refresh')
    #xbmc.executebuiltin(f'Container.Update({plugin.url_for(edit_libraries)})')


@plugin.route('/add_library')
def add_library():
    kb = xbmc.Keyboard("", "Library URL")
    kb.setHiddenInput(False)
    kb.doModal()
    if kb.isConfirmed():
        url = kb.getText()
    else:
        return

    if not url.startswith("https://"):
        url = "https://" + url
    if not url.endswith(".overdrive.com") or not url.endswith(".overdrive.com/"):
        url = url + ".overdrive.com"

    kb = xbmc.Keyboard("", "Username")
    kb.setHiddenInput(False)
    kb.doModal()
    if kb.isConfirmed():
        username = kb.getText()
    else:
        return

    kb = xbmc.Keyboard("", "Password")
    kb.setHiddenInput(False)
    kb.doModal()
    if kb.isConfirmed():
        password = kb.getText()
    else:
        return

    libraries.append({"url": url, "username": username, "password": password})
    save_libraries()
    xbmcgui.Dialog().ok("Overdrive", f"Saved {url}")
    #xbmc.executebuiltin(f'Container.Update({plugin.url_for(index)})')
    xbmc.executebuiltin('Container.Refresh')


if __name__ == '__main__':
    plugin.run()