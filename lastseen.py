#!/usr/bin/env python
"""lastseen-cli is a fairly basic client to update your lastseen time on lastseen.me"""
import sys
import traceback
import requests
from requests.exceptions import HTTPError
import json
import os
from os.path import expanduser
import logging
from logging.handlers import RotatingFileHandler
from getpass import getpass
import daemon
from daemon import pidfile
import psutil
from gi.repository import GObject
import dbus
from dbus.mainloop.glib import DBusGMainLoop

# set our potential testing data
TESTING=False
APP_URL = "https://lastseen.me"

def setup_test(file_name):
    try:
        with open('ls_'+ file_name) as cfg:
            test_obj = json.loads(cfg.read())
            return test_obj
    except FileNotFoundError:
        raise FileNotFoundError(os.environ['LASTSEEN_TESTING'] + ' : ' + file_name + ' data not found')
    except:
        raise Exception(os.environ['LASTSEEN_TESTING'] + ' : ' +file_name + 'data not found, WTF?')

try:
    if os.environ['LASTSEEN_TESTING'] == 'dev':
        test_obj = setup_test('test')
    elif os.environ['LASTSEEN_TESTING'] == 'prod':
        test_obj = setup_test('prod')

    TESTING = True
    APP_URL = test_obj['url']
    EMAIL = test_obj['email']
    PASSWORD = test_obj['passwd']

except KeyError as ke:
    pass

# protect the file descriptors against pyinstaller builds
FDS_TO_MYSELF = []
if getattr(sys, 'frozen', False):
    FDS_TO_MYSELF.extend(
        [of.fd for of in psutil.Process(os.getpid()).open_files()
         if of.path == sys.executable]
    )


def show_help():
    app_help = """valid arguments:
    --config    - setup the client for use. Running this will re-run the entire login process and overwrite any previous
                  config.
    --run       - run the client once. This will check for an existing config file and prompt for one until it exists. 
                  Ctrl+C will get you out.
    --daemon    - once you're happy with the config, use this to launch a daemon that you don't have to worry about.
                  Not a horrible idea to use it in a startup script.
    """
    print(app_help)

class LastSeen(object):
    """ LastSeen cli client class """
    def __init__(self):
        self.user_home = expanduser('~' + '/.lastseen')
        if not os.path.exists(self.user_home):
            os.makedirs(self.user_home)

        self.cfg_file = self.user_home + "/config"
        self.cfg_obj = None
        self.setup_logger()
        self.logger.info("running lastseen cli")

    def setup_logger(self):
        """setup logging """
        # maxBytes = 1kb
        logfh = RotatingFileHandler(self.user_home + '/lastseen.log', mode='a', maxBytes=100000)
        logfh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        logfh.setFormatter(formatter)
        self.logger = logging.getLogger('lastseen')
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(logfh)

    def get_config(self):
        """ actually open/parse/return the config file """
        try:
            with open(self.cfg_file) as cfg:
                self.cfg_obj = json.loads(cfg.read())
                return True
        except FileNotFoundError:
            raise FileNotFoundError('config file not found, please run with --config')
        except:
            raise Exception('invalid config file, please run with --config')


    def load_config(self, fresh=True):
        """ load the config file, running the config method when missing """
        if fresh is not True:
            return self.config()

        try:
            self.get_config()
            return True
        except (IOError, json.JSONDecodeError):
            print("config file [" + self.cfg_file+ "] " +
                  "not found or invalid, let's create it, shall we\n")
            self.config()

    def httpErr(self, err):
        """ handle HTTPError exceptions from requests"""
        self.logger.info(err)

        by = sys._getframe(1).f_code.co_name
        code = err.response.status_code

        default = {
            401: 'Unable to authenicate (from ' + by + ')',
            402: 'Unable to locate destination, please try again later (from ' + by + ')',
            500: "Uh-oh, looks like the server is having a bad hair day. " +
                 "Please try again later or report this if it persists."
        }
        map = {
            'config': {
                401: "Sorry, wrong email/password combination, please try again",
                },
            'run': {
                401: "Unable to authenicate using 'ping', please run --config again"
                },
        }
        msgs = map.get(by, default)
        self.logger.warning( msgs.get(code, default.get(code, "Unknown HTTPError (from " + by + ")") ) )

    def config(self, show_intro=True):
        """ do the actual configuration and save it when valid """
        if show_intro is True:
            print("Welcome to LastSeen\n\nLogin to your account " +
                  "and we'll grab a token to make this seemless.\n")

        if TESTING is True:
            email = EMAIL
            passw = PASSWORD
        else:
            email = input("Email Address: ")
            passw = getpass("We'll use this ONCE to grab a token you can revoke at any time" +
                           "\nPassword: ")

        params = json.dumps({'email': email, 'password': passw}).encode('utf8')
        # grab the token data and save it
        try:
            resp = requests.post(APP_URL + '/api/auth/login', data=params,
                                headers={'content-type': 'application/json',
                                         'Accept': 'application/json'})
            resp.raise_for_status()

            cfg = open(self.cfg_file, 'w')
            token = resp.text
            cfg.write(token)
            cfg.close()
            return True
        except HTTPError as e:
            self.httpErr(e)
            if (e.response.status_code == 401):
                return self.config()

    def run(self):
        """ a single run to update the lastseen time with the server """
        self.get_config()

        params = json.dumps({'token': self.cfg_obj['access_token']}).encode('utf8')
        try:

            resp = requests.post(APP_URL + '/api/pingw', data=params,
                                headers={'content-type': 'application/json',
                                         'Accept': 'application/json'})

            resp.raise_for_status()
            cfg = open(self.cfg_file, 'w')
            # ping will return a refreshed token, so save that for next time
            token = resp.text
            cfg.write(token)
            cfg.close()
            self.logger.info("updated lastseen time and refreshed token")
            return True
        except HTTPError as e:
            self.httpErr(e)

    def filter_cb(self, bus, message):
        """ the dbus filter callback to determine if we should do something """
        if message.get_member() != "ActiveChanged":
            return
        msg_args = message.get_args_list()
        if isinstance(msg_args[0], dbus.Boolean):
            bool_val = bool(msg_args[0])
        else:
            return

        if bool_val is True:
            self.logger.info("ActiveChanged is True (not updating)")
        elif bool_val is False:
            self.run()
        else:
            self.logger.exception(msg_args)

    def run_daemon(self):
        """ starts this client as daemon """
        self.logger.info("starting lastseen daemon")

        self.run()

        pidf = self.user_home + '/lastseen.pid'
        try:
            if os.path.isfile(pidf):
                with open(pidf) as pid_file:
                    pid = int(pid_file.read())

                    if psutil.pid_exists(pid) is False:
                        os.remove(str(pidf))
                        self.logger.info('removed stale pid')
                    else:
                        self.logger.info('lastseen already running, exiting....')
                        return

            for f_h in self.logger.handlers:
                FDS_TO_MYSELF.append(f_h.stream)

            ctx = daemon.DaemonContext(
                chroot_directory=None,
                working_directory=self.user_home+'/',
                pidfile=pidfile.TimeoutPIDLockFile(pidf),
                stdout=sys.stdout,
                stderr=sys.stderr
            )
            ctx.files_preserve = FDS_TO_MYSELF
            with ctx:
                self.logger.info("starting lastseen daemon")
                # go ahead and ping when we startup
                self.run()

                DBusGMainLoop(set_as_default=True)
                bus = dbus.SessionBus()
                bus.add_match_string("type='signal',interface='org.gnome.ScreenSaver'")
                bus.add_message_filter(self.filter_cb)
                mainloop = GObject.MainLoop()
                mainloop.run()
        except:
            self.logger.exception("Unexpected error:" + str(sys.exc_info()[0]))


if __name__ == '__main__':
    LS = LastSeen()

    VALID_ARGS = ['config', 'run', 'daemon']
    ARGS = sys.argv[1:]
    INV = 0
    for i, item in enumerate(ARGS):
        try:
            ARGS[i] = ARGS[i][2:]
            if not ARGS[i] in VALID_ARGS:
                raise Exception()
        except:
            INV += 1 #remove if we're just going to bail
            print("INVALID ARGUMENT(s): %s\n" % " ".join(sys.argv[1:]))
            show_help()
            exit(0)

    if len(ARGS) < 1:
        show_help()
    else:
        try:
            for a in ARGS:
                if a == 'config':
                    LS.config()
                elif a == 'run':
                    LS.run()
                elif a == 'daemon':
                    LS.run_daemon()
                else:
                    print("WTF!?!??!?")
        except KeyboardInterrupt as keyb:
            print("\n\nOkay, bye. Feel free to try again later.")
            sys.exit(0)
        except Exception as ex:
            if TESTING is True:
                print(traceback.format_exc())
                print("Unexpected error: " + type(ex).__name__)
                print ("\t" + ex.args[0])
            else:
                print(ex)
            sys.exit(-1)
