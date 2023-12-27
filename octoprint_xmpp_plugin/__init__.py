import octoprint.plugin
import asyncio, threading
import re
from datetime import datetime
from slixmpp import ClientXMPP
from slixmpp.exceptions import IqError, IqTimeout
from threading import Thread


class Xmpp(
        octoprint.plugin.ShutdownPlugin,
        octoprint.plugin.SettingsPlugin,
        octoprint.plugin.StartupPlugin,
        octoprint.plugin.TemplatePlugin,
        octoprint.plugin.ProgressPlugin,
        octoprint.plugin.core.SortablePlugin,
        ):

    _con = None
    _eventLoop = None
    _gcodeNotifications = dict ()
    _gcodeRe = re.compile(r'{(?P<gc>.*)}{(?P<text>.*)}')

    def on_after_startup(self):
        self._logger.info("user: %s", self._settings.get(["jid"]))
        self._logger.info("to  : %s", self._settings.get(["to"]))
        self.prepare_gcode_notifications()

        self.connect()
        if self._settings.get(["notify","server_start"]):
            self.send_msg("Server started")

        self._logger.info("startup complete")
        return True

    def get_sorting_key(self, context):
        self._logger.info("sorting context  : %s", context)
        return 1

    def on_shutdown(self):
        self._logger.info("shutting down plugin")
        if self._con:
            self.disconnect()
        if self._eventLoop:
            self._eventLoop.stop()
        return True

    def connect(self):
        if self._con:
            self.disconnect()

        id = self._settings.get(["jid"])
        password = self._settings.get(["password"])
        self._logger.info("starting xmpp connection for : %s", id)

        if not self._eventLoop:
            self._eventLoop = asyncio.new_event_loop()

        asyncio.set_event_loop(self._eventLoop)

        self._con = XmppClient(id, password)
        self._con.connect()
        if self._eventLoop.is_running():
            self._logger.info("event loop is running")
        else:
            self._logger.info("eventlooop...")
            thread = Thread(target=self.myProcess, )
            thread.daemon = True
            thread.start();
            self._logger.info("eventlooop... foorked")

        return True

    def myProcess(self):
        self._logger.info("eventlooop thread start...")
        self._eventLoop.run_forever()
        self._logger.info("eventlooop thread run...")
        self._con.process(forever=True)
        self._logger.info("eventlooop thread end...")


    def on_settings_save(self, data):
        self._logger.info("settings changed")
        o_jid = self._settings.get(["jid"])
        o_password = self._settings.get(["password"])
        o_to = self._settings.get(["to"])
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        n_jid = self._settings.get(["jid"])
        n_password = self._settings.get(["password"])
        n_to = self._settings.get(["to"])

        self.prepare_gcode_notifications()

        if self.connect():
            self.send_msg ("XMPP configuration saved ("
                                                      + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                                      + ")")

    def prepare_gcode_notifications(self):
        _gcodeNotifications = dict ()
        if not self._settings.get(["notify","gcodes"]):
            self._logger.info("no custom gcode notifications configured")
            return

        gcodestr = self._settings.get(["notify","gcodes"])
        if gcodestr == "":
            self._logger.info("no gcode notifications configured")
            return

        lines = gcodestr.splitlines()
        for l in lines:
            self.add_gcode(l);


    def add_gcode(self, line):
        line = line.strip()
        if line == "":
            return

        if line.startswith("#"):
            self._logger.info("ignoring comment: %s", line)
            return

        match = self._gcodeRe.search(line)
        if match is None:
            self._logger.info("syntax error in line: %s", line)
            return

        code = match.group('gc')
        text = match.group('text')
        self._gcodeNotifications[code] = text
        self._logger.info("gcode '%s' with notification text '%s' added", code, text)

    def on_gcode_sent(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        if not cmd:
            return

        if not self._gcodeNotifications:
            return

        for code,text in self._gcodeNotifications.items():
            if cmd.startswith(code):
                self.send_msg(text)


    def get_settings_defaults(self):
        return dict(
                jid="user@example.com",
                to="user2@example.com",
                password="",
                notify=dict(
                    msg_prefix="",
                    server_start=False,
                    print_start=True,
                    print_end=True,
                    percent_progress=10,
                    gcodes="#{M0}{Print paused}\n#{M600}{Change filament started}"
                    )
                )

    def get_settings_restricted_paths(self):
        return { 'user':[["jid"],["to"],["password"],], }


    def get_template_configs(self):
        return [ dict(type="settings", custom_bindings=False) ]

    def disconnect(self):
        try:
            if not self._con:
                return

            self._logger.info("disconnect")
            self._con.disconnect()
            self._con = None
            return True
        except:
            self._logger.info("disconnect failed")
            self._con = None
            return False

    def send_msg(self, msg):
        try:
            to = self._settings.get(["to"])
            prefix = self._settings.get(["notify", "msg_prefix"])
            if prefix != "":
                msg = prefix + ": " + msg
            self._logger.info("sending message '%s' to %s", msg, to)
            self._con.send_message(mto=to, mbody=msg, mtype='chat')
        except:
            self._logger.info("send message failed")

    def on_print_progress(self, storage, path, progress):
        percent = self._settings.get_int(["notify", "percent_progress"])

        if progress == 0 and self._settings.get(["notify", "print_start"]):
            self.send_msg("Print {0} started".format(path))
        if percent > 0 and progress != 0 and progress % percent == 0:
            self.send_msg("{0}: {1}% complete".format(path, progress))
        if progress >= 100 and self._settings.get(["notify", "print_end"]):
            self.send_msg("Print {0} completed".format(path))


    def get_update_information(self, *args, **kwargs):
        self._logger.info("return update information")
        return dict(
                updateplugindemo=dict(
                    displayName=self._plugin_name,
                    displayVersion=self._plugin_version,

                    type="github_release",
                    current=self._plugin_version,
                    user="tobser",
                    repo="octoprint-xmpp-plugin",
                    pip="https://github.com/tobser/octoprint-xmpp-plugin/archive/main.zip"
                    )
                )


class XmppClient(ClientXMPP):

    def __init__(self, jid, password):
        ClientXMPP.__init__(self, jid, password)

        self.add_event_handler("session_start", self.session_start)
        self.add_event_handler("message", self.message)

        self.register_plugin('xep_0030')
        self.register_plugin('xep_0066') # OOB
        self.register_plugin('xep_0231') # BOB

    def session_start(self, event):
        self.send_presence()
        self.get_roster()

    def message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            msg.reply("Thanks for sending\n%(body)s" % msg).send()

def __plugin_load__():
    plugin = Xmpp()

    global __plugin_implementation__
    __plugin_implementation__ = plugin

    global __plugin_hooks__
    __plugin_hooks__ = {
            "octoprint.comm.protocol.gcode.sent": plugin.on_gcode_sent,
            "octoprint.plugin.softwareupdate.check_config": plugin.get_update_information,
            }

__plugin_name__ = "XMPP Plugin"
__plugin_pythoncompat__ = ">=3.7,<4"
__plugin_implementation__ = Xmpp()
