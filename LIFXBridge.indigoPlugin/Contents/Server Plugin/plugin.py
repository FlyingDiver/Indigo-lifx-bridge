#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import socket
import time
from random import randint
import json
import logging

from lifxlan.msgtypes import *
from lifxlan.unpack import unpack_lifx_message
from lifxlan.message import Message, BROADCAST_MAC, HEADER_SIZE_BYTES, little_endian
from lifxlan.device import UDP_BROADCAST_IP, UDP_BROADCAST_PORT

from ghpu import GitHubPluginUpdater

PUBLISHED_KEY = "published"
ALT_NAME_KEY = "alternate-name"
MAC_KEY = "fakeMAC"
TARGET_KEY = "target"

DEFAULT_LIFX_PORT = 56700

def fakeMAC(deviceID):
    hexString = format(deviceID,'08x')
    macString = ':'.join(s.encode('hex') for s in hexString.decode('hex'))
    return "00:16:"+ macString


################################################################################
class Plugin(indigo.PluginBase):
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(u"logLevel = " + str(self.logLevel))

    def startup(self):
        self.logger.info(u"Starting LIFX Bridge")

        self.updater = GitHubPluginUpdater(self)
        self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "24")) * 60.0 * 60.0
        self.logger.debug(u"updateFrequency = " + str(self.updateFrequency))
        self.next_update_check = time.time()

        self.seen_msg_list = [-1, -1, -1, -1, -1, -1]

        self.refreshDeviceList()

        # Need to subscribe to device changes here so we can call the refreshDeviceList method
        # in case there was a change or deletion of a device that's published
        indigo.devices.subscribeToChanges()

        try :
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        except socket.error, msg :
            self.logger.error('Failed to create socket. Error Code : ' + str(msg[0]) + ' Message ' + msg[1])
            return

        try:
            self.sock.bind(('', DEFAULT_LIFX_PORT))
            self.sock.settimeout(1)
        except socket.error , msg:
            self.logger.error('Bind failed. Error Code : ' + str(msg[0]) + ' Message ' + msg[1])
            return

    def shutdown(self):
        self.logger.info(u"Shutting down LIFX Bridge")
        self.sock.close()

    def runConcurrentThread(self):

        try:
            while True:

                if (self.updateFrequency > 0.0) and (time.time() > self.next_update_check):
                    self.next_update_check = time.time() + self.updateFrequency
                    self.updater.checkForUpdate()

                if len(self.publishedDevices) > 0:      # no need to respond if there aren't any devices to emulate

                    try:
                        data, (ip_addr, port) = self.sock.recvfrom(1024)
                    except socket.timeout:
                        pass
                    except socket.error , msg:
                        self.logger.error('Socket recvfrom failed. Error Code : ' + str(msg[0]) + ' Message ' + msg[1])
                    else:
                        message = unpack_lifx_message(data)
                        self.lifxRespond(message, ip_addr, port)

                    self.sleep(0.1)     # short sleep while looking for inbound requests

                else:
                    self.sleep(1.0)     # longer sleep when not looking for LIFX requests

        except self.stopThread:
            pass



    ########################################
    # Prefs dialog methods
    ########################################
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(u"logLevel = " + str(self.logLevel))

    ########################################
    # The next two methods should catch when a device name changes in Indigo and when a device we have published
    # gets deleted - we'll just rebuild the device list cache in those situations.
    ########################################
    def deviceDeleted(self, dev):
        self.logger.debug(u"deviceDeleted called")
        if dev.id in self.publishedDevices:
            self.logger.info(u"A device (%s) that was published has been deleted." % dev.name)
            self.refreshDeviceList()

    def deviceUpdated(self, origDev, newDev):
        #self.logger.debug(u"deviceUpdated called with id: %i" % origDev.id)
        if origDev.id in self.publishedDevices:
            # Drill down on the change a bit - if the name changed and there's no alternate name OR the alternate
            # name changed then refresh the device list
            if ALT_NAME_KEY in origDev.pluginProps or ALT_NAME_KEY in newDev.pluginProps:
                if origDev.pluginProps.get(ALT_NAME_KEY, None) != newDev.pluginProps.get(ALT_NAME_KEY, None):
                    self.refreshDeviceList()
                    self.logger.info(u"A device alternative name changed.")
            elif origDev.name != newDev.name:
                self.refreshDeviceList()
                self.logger.info(u"A device name changed.")
            elif origDev.pluginProps.get(PUBLISHED_KEY, "False") != newDev.pluginProps.get(PUBLISHED_KEY, "False"):
                self.refreshDeviceList()
                self.logger.info(u"Your published device list changed.")

    ########################################
    # This method is called to refresh the list of published devices.
    ########################################
    def refreshDeviceList(self):
        self.logger.debug(u"refreshDeviceList called")
        self.publishedDevices = dict()
        for dev in indigo.devices:
            props = dev.pluginProps
            if PUBLISHED_KEY in props:
                self.publishedDevices[dev.id] = props.get(ALT_NAME_KEY, "")
                self.logger.debug(u"found published device: %i - %s (%s) - %s" % (dev.id, dev.name, self.publishedDevices[dev.id], props[MAC_KEY]))
        self.logger.debug(u"%i devices published" % len(self.publishedDevices))

    ########################################
    # This method is called to generate a list of devices that support onState only.
    ########################################
    def devicesWithOnState(self, filter="", valuesDict=None, typeId="", targetId=0):
        # A little bit of Python list comprehension magic here. Basically, it iterates through
        # the device list and only adds the device if it has an onState property.
        return [(dev.id, dev.name) for dev in indigo.devices if hasattr(dev, "onState")]

    ########################################
    # These are the methods that's called when devices are selected from the various lists/menus. They enable other
    # as necessary.
    ########################################
    def selectDeviceToAdd(self, valuesDict, typeId=None, devId=None):
        self.logger.debug(u"selectDeviceToAdd called")
        valuesDict["enableAltNameField"] = True
        if "sourceDeviceMenu" in valuesDict:
            # Get the device ID of the selected device
            deviceId = valuesDict["sourceDeviceMenu"]
            # If the device id isn't empty (should never be)
            if deviceId != "":
                # Get the device instance
                dev = indigo.devices[int(deviceId)]
                try:
                    # Try getting the existing alternate name and set the alt field with the correct name
                    altName = dev.pluginProps[ALT_NAME_KEY]
                    valuesDict["altName"] = altName
                except:
                    # It's not there, so just skip
                    pass
        else:
            valuesDict["altName"] = ""
        return valuesDict

    ########################################
    # This is the method that's called by the Add Device button in the config dialog.
    ########################################
    def addDevice(self, valuesDict, typeId=None, devId=None):
        self.logger.debug(u"addDevice called")
        # Get the device ID of the selected device - bail if it's not good
        try:
            deviceId = int(valuesDict.get("sourceDeviceMenu", 0))
        except:
            deviceId = 0
        if deviceId == 0:
            return

        # Get the list of devices that have already been added to the list
        # If the key doesn't exist then return an empty string indicating
        # no devices have yet been added. "memberDevices" is a hidden text
        # field in the dialog that holds a comma-delimited list of device
        # ids, one for each of the devices in the scene.
        self.logger.debug(u"adding device: %s" % deviceId)
        # Get the list of devices that are already in the scene
        # Add or update the name to the plugin's cached list
        self.publishedDevices[deviceId] = valuesDict["altName"]
        # Next, we need to add the properties to the device for permanent storage
        # Get the device instance
        dev = indigo.devices[deviceId]
        # Get the device's props
        props = dev.pluginProps
        # Add the flag to the props. May already be there, but no harm done.
        props[PUBLISHED_KEY] = "True"
        # Add/update the name to the props.
        self.logger.debug(u"addDevice: valuesDict['altName']: |%s|" % str(valuesDict["altName"]))
        if len(valuesDict["altName"]):
            props[ALT_NAME_KEY] = valuesDict["altName"]
        elif ALT_NAME_KEY in props:
            del props[ALT_NAME_KEY]

        # add a fake MAC address to the props
        props[MAC_KEY] = fakeMAC(deviceId)

        # Replace the props on the server's copy of the device instance.
        dev.replacePluginPropsOnServer(props)
        self.logger.debug(u"valuesDict = " + str(valuesDict))
        # Clear out the name field and the source device field
        valuesDict["sourceDeviceMenu"] = ""
        valuesDict["enableAltNameField"] = "False"
        # Clear out the alternate name field
        valuesDict["altName"] = ""
        return valuesDict

    ########################################
    # This is the method that's called by the Delete Device button in the scene
    # device config UI.
    ########################################
    def deleteDevices(self, valuesDict, typeId=None, devId=None):
        self.logger.debug(u"deleteDevices called")
        # Delete the device's properties for this plugin and delete the entry in self.publishedDevices
        for devId in valuesDict['memberDeviceList']:
            del self.publishedDevices[int(devId)]
            dev = indigo.devices[int(devId)]
            # Setting a device's plugin props to None will completely delete the props for this plugin in the devices'
            # globalProps.
            dev.replacePluginPropsOnServer(None)
        return valuesDict

    ########################################
    # This is the method that's called to build the member device list. Note
    # that valuesDict is read-only so any changes you make to it will be discarded.
    ########################################
    def memberDevices(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.debug(u"memberDevices called with filter: %s  typeId: %s  targetId: %s" % (filter, typeId, str(targetId)))
        returnList = list()
        for id, name in self.publishedDevices.items():
            deviceName = indigo.devices[id].name
            if len(name) > 0:
                deviceName += " (%s)" % name
            returnList.append((id, deviceName))
            returnList = sorted(returnList, key= lambda item: item[1])
        return returnList

    ########################################
    # Actions defined in MenuItems.xml:
    ########################################
    def toggleDebugging(self):
        if self.debug:
            self.logger.info(u"Turning off debug logging")
            self.pluginPrefs["showDebugInfo"] = False
        else:
            self.logger.info(u"Turning on debug logging")
            self.pluginPrefs["showDebugInfo"] = True
        self.debug = not self.debug

    def checkForUpdates(self):
        self.updater.checkForUpdate()

    def updatePlugin(self):
        self.updater.update()

    def forceUpdate(self):
        self.updater.update(currentVersion='0.0.0')

    ########################################
    #   Methods that deal with LIFX protocol messages
    ########################################

    def lifxRespond(self, message, ip_addr, port):

        source = message.source_id
        seq_num = message.seq_num

        if seq_num in self.seen_msg_list:

            self.debugLog("lifxRespond, skipping repeat seq_num = %d, type = %d, target = %s" % (seq_num, message.message_type,  message.target_addr))
            return

        elif seq_num == 0:
            pass
        else:
            self.seen_msg_list.pop(0)
            self.seen_msg_list.append(seq_num)

        self.debugLog("lifxRespond, seq_num = %d, type = %d, target = %s" % (seq_num, message.message_type,  message.target_addr))

        if message.message_type == MSG_IDS[GetService]:                                                     # 2

            payload = {"service": "1", "port": "56700"}

            for devID, alias in self.publishedDevices.items():
                self.logger.debug("GetService message, replying for: " + indigo.devices[devID].name)
                target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                replyMessage = StateService(target_addr, source, seq_num, payload, False, False)
                self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                if message.ack_requested:
                    self.logger.debug("GetService message, sending Ack ")
                    replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                    self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

            # repeat with service 5?  The bulbs do.


        elif message.message_type == MSG_IDS[StateService]:                                                 # 3

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug("StateService message for device " + devID + " - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetHostInfo]:                                                  # 12

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug("GetHostInfo message, replying for: " + indigo.devices[devID].name)

                    payload = {"signal":"0","tx":"0","rx":"0","reserved1":"0"}
                    replyMessage = StateHostInfo(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[StateHostInfo]:                                                # 13

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug("StateHostInfo message for device " + devID + " - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetHostFirmware]:                                              # 14

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug("GetHostFirmware message, replying for: " + indigo.devices[devID].name)

                    payload = {"build":"1428977151000000000","reserved1":"1428977151000000000","version":"65538"}
                    replyMessage = StateHostFirmware(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[StateHostFirmware]:                                            # 15

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug("StateHostFirmware message for device " + devID + " - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetWifiInfo]:                                                  # 16

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:   # reply with info for requested device

                    self.logger.debug("GetWifiInfo message, replying for: " + indigo.devices[devID].name)

                    payload = {"signal":"944912011","tx":"3397400","rx":"23670","reserved1":"3010"}
                    replyMessage = StateWifiInfo(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[StateWifiInfo]:                                                # 17

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug("StateWifiInfo message for device " + devID + " - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetWifiFirmware]:                                              # 18

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:   # reply with info for requested device

                    self.logger.debug("GetWifiFirmware message, replying for: " + indigo.devices[devID].name)

                    payload = {"build":"0","reserved1":"0","version":"6619161"}
                    replyMessage = StateWifiFirmware(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[StateWifiFirmware]:                                            # 19

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug("StateWifiFirmware message for device " + devID + " - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetPower]:                                                     # 20

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:   # reply with info for requested device

                    self.logger.debug("GetPower message, replying for: " + indigo.devices[devID].name)

                    payload = {"power_level":self.getDevicePower(devID)}
                    replyMessage = StatePower(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[SetPower]:                                                     # 21

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug("SetPower message  for: " + indigo.devices[devID].name)

                    for field in message.payload_fields:
                        if field[0] == "Power":
                            self.turnOnOffDevice(devID, field[1])
                            break

            if message.ack_requested:
                replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

            if message.response_requested:
                payload = {"power_level":self.getDevicePower(devID)}
                replyMessage = StatePower(message.target_addr, source, seq_num, payload, False, False)
                self.sock.sendto(replyMessage.packed_message,(ip_addr, port))


        elif message.message_type == MSG_IDS[StatePower]:                                                   # 22

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug("StatePower message for device " + devID + " - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetLabel]:                                                     # 23

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY] or message.tagged:

                    self.logger.debug("GetLabel message, replying for: " + indigo.devices[devID].name)

                    try:
                        label = indigo.devices[devID].pluginProps[ALT_NAME_KEY]
                    except:
                        label = indigo.devices[devID].name

                    payload = {"label":label}
                    replyMessage = StateLabel(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[SetLabel]:                                                     # 24
            self.logger.debug("SetLabel message - not supported!")

            if message.ack_requested:
                for devID, alias in self.publishedDevices.items():

                    if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:   # reply with info for requested device

                        replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

            if message.response_requested:
                self.logger.debug("Oops!  Client wants a response to SetLabel")

        elif message.message_type == MSG_IDS[StateLabel]:                                                   # 25

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug("StateLabel message for device " + devID + " - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK to StateLabel")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response to StateLabel")

        elif message.message_type == MSG_IDS[GetVersion]:                                                   # 32

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:   # reply with info for requested device

                    self.logger.debug("GetVersion message, replying for: " + indigo.devices[devID].name)

                    payload = {"vendor":"1","product":"10","version":"0"}
                    replyMessage = StateVersion(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[StateVersion]:                                                 # 33

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug("StateVersion message for device " + devID + " - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetInfo]:                                                      # 34

            time_s = str(int(time.time() * 1000000000))

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:   # reply with info for requested device

                    self.logger.debug("GetInfo message, replying for: " + indigo.devices[devID].name)

                    payload = {"time":time_s,"uptime":"1243200000000","downtime":"0"}
                    replyMessage = StateInfo(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[StateInfo]:                                                    # 35

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug("StateInfo message for device " + devID + " - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[Acknowledgement]:                                              # 45
            self.logger.debug("\nGot an ACK message.  Don't know why.")
            if message.ack_requested:
                self.logger.debug("Oops!  Client wants an ACK")
            if message.response_requested:
                self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[EchoRequest]:                                                  # 58

            payload = message.payload_fields
            for devID, alias in self.publishedDevices.items():

                self.logger.debug("EchoRequest message, replying for: " + indigo.devices[devID].name)

                target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                replyMessage = EchoReply(target_addr, source, seq_num, payload, False, False)
                self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                if message.ack_requested:
                    replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                    self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[EchoResponse]:                                                 # 59
            self.logger.debug("\nGot an EchoResponse message.  Don't know why.")
            if message.ack_requested:
                self.logger.debug("Oops!  Client wants an ACK")
            if message.response_requested:
                self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[LightGet]:                                                     # 101

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY] or message.tagged:

                    self.logger.debug("LightGet message, replying for: " + indigo.devices[devID].name)

                    try:
                        label = indigo.devices[devID].pluginProps[ALT_NAME_KEY]
                    except:
                        label = indigo.devices[devID].name

                    payload = {"color": ("16200", "130", self.getDeviceBrightness(devID), "3000"),"reserved1":"0","power_level":self.getDevicePower(devID),"label":label,"reserved2":"0"}
                    target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                    replyMessage = LightState(target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[LightSetColor]:                                                # 102

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug("LightSetColor command is for device: " + indigo.devices[devID].name + ", payload = " + str(message.payload_fields))

                    for field in message.payload_fields:
                        if field[0] == "Color":
                            (hue, saturation, brightness, color) = field[1]
                            self.setDeviceBrightness(devID, brightness)
                            break

                    if message.ack_requested:
                        target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                    if message.response_requested:
                        payload = {"color": ("16200", "130", self.getDeviceBrightness(devID), "3000"),"reserved1":"0","power_level":self.getDevicePower(devID),"label":label,"reserved2":"0"}
                        target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                        replyMessage = LightState(target_addr, source, seq_num, payload, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[LightState]:                                                   # 107

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug("LightState message for device " + devID + " - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[LightGetPower]:                                                # 116

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY] or message.tagged:

                    self.logger.debug("LightGetPower message, replying for: " + indigo.devices[devID].name)

                    payload = {"power_level":self.getDeviceBrightness(devID)}
                    target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                    replyMessage = LightStatePower(target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[LightSetPower]:                                                # 117

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug("LightSetPower command is for device: " + indigo.devices[devID].name + ", payload = " + str(message.payload_fields))

                    for field in message.payload_fields:
                        if field[0] == "Power":
                            self.turnOnOffDevice(devID, field[1])
                            break

                    if message.ack_requested:
                        target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

                    if message.response_requested:
                        payload = {"power_level":self.getDevicePower(devID)}
                        target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                        replyMessage = LightStatePower(target_addr, source, seq_num, payload, False, False)
                        self.sock.sendto(replyMessage.packed_message,(ip_addr, port))

        elif message.message_type == MSG_IDS[LightStatePower]:                                              # 118

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug("LightStatePower message for device " + devID + " - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        else:
            self.logger.debug("Uknown message type from " + ip_addr + ":" + str(port) + ":\n" + str(message))


    ########################################
    # Method called from lifxRespond() to turn on/off a device
    #
    #   deviceId is the ID of the device in Indigo
    #   turnOn is a boolean to indicate on/off
    ########################################
    def turnOnOffDevice(self, deviceId, turnOn):
        self.logger.info(u"Set on state of device %i to %s" % (deviceId, str(turnOn)))
        try:
            if turnOn:
                indigo.device.turnOn(deviceId)
            else:
                indigo.device.turnOff(deviceId)
        except:
            self.logger.error(u"Device with id %i doesn't exist. The device list will be rebuilt." % deviceId)
            self.refreshDeviceList()

    ########################################
    # Method called from lifxRespond() to set brightness of a device
    #
    #   deviceId is the ID of the device in Indigo
    #   brightness is the brightness in the range 0-100
    ########################################
    def setDeviceBrightness(self, deviceId, brightness):
        try:
            dev = indigo.devices[deviceId]
        except:
            self.logger.error(u"Device with id %i doesn't exist. The device list will be rebuilt." % deviceId)
            self.refreshDeviceList()
            return
        if isinstance(dev, indigo.DimmerDevice):
            self.logger.info(u"Set brightness of device %i to %i" % (deviceId, brightness))
            indigo.dimmer.setBrightness(dev, value=brightness)
        else:
            self.logger.info(u"Device with id %i doesn't support dimming." % deviceId)

    ########################################
    # Method called from lifxRespond() to get the brightness of a device
    #
    #   deviceId is the ID of the device in Indigo
    #   brightness is in the range 0-65535 (LIFX range)
    ########################################
    def getDeviceBrightness(self, deviceId):
        try:
            dev = indigo.devices[deviceId]
        except:
            self.logger.error(u"Device with id %i doesn't exist. The device list will be rebuilt." % deviceId)
            self.refreshDeviceList()
            return

        if isinstance(dev, indigo.DimmerDevice):
            return int((float(dev.brightness) / 100.0) * 65535)
        else:
            return int(dev.onState) * 65535

    ########################################
    # Method called from lifxRespond() to get the brightness of a device
    #
    #   deviceId is the ID of the device in Indigo
    #   brightness is in the range 0-65535 (LIFX range)
    ########################################
    def getDevicePower(self, deviceId):
        try:
            dev = indigo.devices[deviceId]
        except:
            self.logger.error(u"Device with id %i doesn't exist. The device list will be rebuilt." % deviceId)
            self.refreshDeviceList()
            return
        return int(dev.onState) * 65535
