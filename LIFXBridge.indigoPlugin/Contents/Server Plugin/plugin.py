#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import socket
import time
from random import randint
import json
import logging
import colorsys
import os
import base64
import re

from lifxlan.msgtypes import *
from lifxlan.unpack import unpack_lifx_message
from lifxlan.message import Message, BROADCAST_MAC, HEADER_SIZE_BYTES, little_endian

PUBLISHED_KEY = "published"
ALT_NAME_KEY = "alternate-name"
MAC_KEY = "fakeMAC"
TARGET_KEY = "target"
LOCATION_KEY = "location"

DEFAULT_LIFX_PORT = 56700

def fakeMAC(deviceID):
    hexString = format(deviceID, '08x')
    macString = ':'.join(re.findall('..', hexString))
    return f"00:16:{macString}"


################################################################################
class Plugin(indigo.PluginBase):
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)
        self.logLevel = int(pluginPrefs.get("logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(f"logLevel = {self.logLevel}")

        self.seen_msg_list = [-1, -1, -1, -1, -1, -1]
        self.publishedDevices = dict()

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except socket.error as msg:
            self.logger.error(f"Failed to create socket. Error Code : {msg[0]}, Message: {msg[1]}")
            return

        try:
            self.sock.bind(('', DEFAULT_LIFX_PORT))
            self.sock.settimeout(2)
        except socket.error as msg:
            self.logger.error(f"LIFX port bind failed. Error Code : {msg[0]}, Message: {msg[1]}")
            return

    def startup(self):
        self.logger.info("Starting LIFX Bridge")
        self.refreshDeviceList()
        indigo.devices.subscribeToChanges()

    def shutdown(self):
        self.logger.info("Shutting down LIFX Bridge")
        self.sock.close()

    def runConcurrentThread(self):
        try:
            while True:
                if len(self.publishedDevices) > 0:  # no need to respond if there aren't any devices to emulate
                    try:
                        data, (ip_addr, port) = self.sock.recvfrom(2048)
                    except socket.timeout:
                        pass
                    except socket.error as msg:
                        self.logger.error(f"Socket recvfrom failed. Error Code : {msg[0]}, Message {msg[1]}")
                    else:
                        message = unpack_lifx_message(data)
                        self.lifxRespond(message, ip_addr, port)
                    self.sleep(0.1)  # short sleep while looking for inbound requests
                else:
                    self.sleep(1.0)  # longer sleep when not looking for LIFX requests
        except self.StopThread:
            pass

    ########################################
    # Prefs dialog methods
    ########################################
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(f"logLevel = {self.logLevel}")

    ########################################
    # The next two methods should catch when a device name changes in Indigo and when a device we have published
    # gets deleted - we'll just rebuild the device list cache in those situations.
    ########################################
    def deviceDeleted(self, dev):
        if dev.id in self.publishedDevices:
            self.logger.info(f"A device ({dev.name}) that was published has been deleted.")
            self.refreshDeviceList()

    def deviceUpdated(self, origDev, newDev):
        if origDev.id in self.publishedDevices:
            # Drill down on the change a bit - if the name changed and there's no alternate name OR the alternate
            # name changed then refresh the device list
            if ALT_NAME_KEY in origDev.pluginProps or ALT_NAME_KEY in newDev.pluginProps:
                if origDev.pluginProps.get(ALT_NAME_KEY, None) != newDev.pluginProps.get(ALT_NAME_KEY, None):
                    self.refreshDeviceList()
                    self.logger.debug("A device alternative name changed.")
            elif origDev.name != newDev.name:
                self.refreshDeviceList()
                self.logger.debug("A device name changed.")
            elif origDev.pluginProps.get(PUBLISHED_KEY, "False") != newDev.pluginProps.get(PUBLISHED_KEY, "False"):
                self.refreshDeviceList()
                self.logger.debug("Your published device list changed.")

    ########################################
    # This method is called to refresh the list of published devices.
    ########################################
    def refreshDeviceList(self):
        self.logger.debug("refreshDeviceList called")
        for dev in indigo.devices:
            props = dev.pluginProps
            if PUBLISHED_KEY in props:
                self.publishedDevices[dev.id] = props.get(ALT_NAME_KEY, "")
                self.logger.debug(f"found published device: {dev.id:d} - {dev.name} ({self.publishedDevices[dev.id]}) - {props[MAC_KEY]}")
                if not props.get(LOCATION_KEY, None):
                    props[LOCATION_KEY] = base64.b64encode(bytearray(os.urandom(16)))
                    dev.replacePluginPropsOnServer(props)
        self.logger.debug(f"{len(self.publishedDevices):d} devices published")

    ########################################
    # This method is called to generate a list of devices that support onState only.
    ########################################
    @staticmethod
    def devicesWithOnState(filter="", valuesDict=None, typeId="", targetId=0):
        return [(dev.id, dev.name) for dev in indigo.devices if hasattr(dev, "onState")]

    ########################################
    # These are the methods that's called when devices are selected from the various lists/menus. They enable other as necessary.
    ########################################
    @staticmethod
    def selectDeviceToAdd(valuesDict, typeId=None, devId=None):
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
                except (Exception,):
                    # It's not there, so just skip
                    pass
        else:
            valuesDict["altName"] = ""
        return valuesDict

    ########################################
    # This is the method that's called by the Add Device button in the config dialog.
    ########################################
    def addDevice(self, valuesDict, typeId=None, devId=None):
        # Get the device ID of the selected device - bail if it's not good
        deviceId = int(valuesDict.get("sourceDeviceMenu", 0))
        if deviceId == 0:
            return

        # Get the list of devices that have already been added to the list
        # If the key doesn't exist then return an empty string indicating
        # no devices have yet been added. "memberDevices" is a hidden text
        # field in the dialog that holds a comma-delimited list of device
        # ids, one for each of the devices in the scene.
        self.logger.debug(f"adding device: {deviceId}")
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
        self.logger.debug(f"addDevice: valuesDict['altName']: |{valuesDict['altName']}|")
        if len(valuesDict["altName"]):
            props[ALT_NAME_KEY] = valuesDict["altName"]
        # hack to get around Harmony bug that doesn't like Unicode names
        elif not all(ord(char) < 128 for char in dev.name):
            alias = ''.join(i if ord(i) < 128 else "_" for i in dev.name)
            self.logger.info(f"Forcing alias '{alias}' for '{dev.name}' (Harmony requires non-Unicode names)")
            props[ALT_NAME_KEY] = alias
        elif ALT_NAME_KEY in props:
            del props[ALT_NAME_KEY]

        # add a fake MAC address and random location array to the props
        props[MAC_KEY] = fakeMAC(deviceId)
        props[LOCATION_KEY] = base64.b64encode(bytearray(os.urandom(16)))

        # Replace the props on the server's copy of the device instance.
        dev.replacePluginPropsOnServer(props)
        self.logger.threaddebug(f"valuesDict = {valuesDict}")
        # Clear out the name field and the source device field
        valuesDict["sourceDeviceMenu"] = ""
        valuesDict["enableAltNameField"] = "False"
        # Clear out the alternate name field
        valuesDict["altName"] = ""
        return valuesDict

    ########################################
    # This is the method that's called by the "Delete Device "button in the scene device config UI.
    ########################################
    def deleteDevices(self, valuesDict, typeId=None, devId=None):
        self.logger.debug("deleteDevices called")
        # Delete the device's properties for this plugin and delete the entry in self.publishedDevices
        for devId in valuesDict['memberDeviceList']:
            del self.publishedDevices[int(devId)]
            dev = indigo.devices[int(devId)]
            # Setting a device's plugin props to None will completely delete the props for this plugin in the devices' globalProps.
            dev.replacePluginPropsOnServer(None)
        return valuesDict

    ########################################
    # This is the method that's called to build the member device list. Note
    # that valuesDict is read-only so any changes you make to it will be discarded.
    ########################################
    def memberDevices(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.debug(f"memberDevices called with filter: {filter}  typeId: {typeId}  targetId: {targetId}")
        returnList = list()
        for did, name in self.publishedDevices.items():
            deviceName = indigo.devices[did].name
            if len(name) > 0:
                deviceName += " (%s)" % name
            returnList.append((did, deviceName))
            returnList = sorted(returnList, key=lambda item: item[1])
        return returnList

    ########################################
    # Actions defined in MenuItems.xml:
    ########################################
    def listDevices(self):
        self.logger.info(f"{'Indigo DevID':<16}  {'LIFX Address':<20} {'Indigo Name (alias)':<30}")
        for did, name in self.publishedDevices.items():
            fMAC = indigo.devices[did].pluginProps[MAC_KEY]
            deviceName = indigo.devices[did].name
            if len(name) > 0:
                deviceName = f"{deviceName} ({name})"
            self.logger.info(f"{did:<16}  {fMAC:20} {deviceName:30}")

    ########################################
    #   Methods that deal with LIFX protocol messages
    ########################################

    def lifxRespond(self, message, ip_addr, port):

        source = message.source_id
        seq_num = message.seq_num

        if seq_num in self.seen_msg_list:

            self.logger.threaddebug(f"lifxRespond, skipping repeat seq_num = {seq_num:d}, type = {message.message_type:d}, target = {message.target_addr}")
            return

        elif seq_num == 0:
            pass
        else:
            self.seen_msg_list.pop(0)
            self.seen_msg_list.append(seq_num)

        self.logger.threaddebug(f"lifxRespond: message = \n{message}")

        if message.message_type == MSG_IDS[GetService]:  # 2

            payload = {"service": "1", "port": "56700"}

            for devID, alias in self.publishedDevices.items():
                self.logger.debug(f"GetService message, replying for: {indigo.devices[devID].name}")
                target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                replyMessage = StateService(target_addr, source, seq_num, payload, False, False)
                self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                if message.ack_requested:
                    self.logger.debug("GetService message, sending Ack ")
                    replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

            # repeat with service 5?  The bulbs do.

        elif message.message_type == MSG_IDS[StateService]:  # 3

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug(f"StateService message for device {devID} - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetHostInfo]:  # 12

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug(f"GetHostInfo message, replying for: {indigo.devices[devID].name}")

                    payload = {"signal": "0", "tx": "0", "rx": "0", "reserved1": "0"}
                    replyMessage = StateHostInfo(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[StateHostInfo]:  # 13

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug(f"StateHostInfo message for device {devID} - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetHostFirmware]:  # 14

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug(f"GetHostFirmware message, replying for: {indigo.devices[devID].name}")

                    payload = {"build": "1428977151000000000", "reserved1": "1428977151000000000", "version": "65538"}
                    replyMessage = StateHostFirmware(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[StateHostFirmware]:  # 15

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug(f"StateHostFirmware message for device {devID} - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetWifiInfo]:  # 16

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:  # reply with info for requested device

                    self.logger.debug(f"GetWifiInfo message, replying for: {indigo.devices[devID].name}")

                    payload = {"signal": "944912011", "tx": "3397400", "rx": "23670", "reserved1": "3010"}
                    replyMessage = StateWifiInfo(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[StateWifiInfo]:  # 17

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug(f"StateWifiInfo message for device {devID} - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetWifiFirmware]:  # 18

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:  # reply with info for requested device

                    self.logger.debug(f"GetWifiFirmware message, replying for: {indigo.devices[devID].name}")

                    payload = {"build": "0", "reserved1": "0", "version": "6619161"}
                    replyMessage = StateWifiFirmware(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[StateWifiFirmware]:  # 19

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug(f"StateWifiFirmware message for device {devID} - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetPower]:  # 20

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:  # reply with info for requested device

                    self.logger.debug(f"GetPower message, replying for: {indigo.devices[devID].name}")

                    payload = {"power_level": self.getDevicePower(devID)}
                    replyMessage = StatePower(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[SetPower]:  # 21

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug(f"SetPower message for: {indigo.devices[devID].name}")

                    for field in message.payload_fields:
                        if field[0] == "Power":
                            self.turnOnOffDevice(devID, field[1])
                            break

            if message.ack_requested:
                replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

            if message.response_requested:
                payload = {"power_level": self.getDevicePower(devID)}  # noqa
                replyMessage = StatePower(message.target_addr, source, seq_num, payload, False, False)
                self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[StatePower]:  # 22

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug(f"StatePower message for device {devID} - not supported!")
                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetLabel]:  # 23

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY] or message.tagged:

                    self.logger.debug(f"GetLabel message, replying for: {indigo.devices[devID].name}")

                    try:
                        label = indigo.devices[devID].pluginProps[ALT_NAME_KEY]
                    except (Exception,):
                        label = indigo.devices[devID].name

                    payload = {"label": label}
                    replyMessage = StateLabel(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[SetLabel]:  # 24
            self.logger.debug("SetLabel message - not supported!")

            if message.ack_requested:
                for devID, alias in self.publishedDevices.items():

                    if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:  # reply with info for requested device

                        replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

            if message.response_requested:
                self.logger.debug("Oops!  Client wants a response to SetLabel")

        elif message.message_type == MSG_IDS[StateLabel]:  # 25

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug(f"StateLabel message for device {devID} - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK to StateLabel")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response to StateLabel")

        elif message.message_type == MSG_IDS[GetVersion]:  # 32

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:  # reply with info for requested device

                    self.logger.debug(f"GetVersion message, replying for: {indigo.devices[devID].name}")

                    if isinstance(indigo.devices[devID], indigo.DimmerDevice):

                        if indigo.devices[devID].supportsRGB:
                            product = "22"  # Color 1000
                        else:
                            product = "10"  # White 800 (Low Voltage)

                    else:
                        product = "10"  # White 800 (Low Voltage)

                    payload = {"vendor": "1", "product": product, "version": "0"}
                    replyMessage = StateVersion(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[StateVersion]:  # 33

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug(f"StateVersion message for device {devID} - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetInfo]:  # 34

            time_s = str(int(time.time() * 1000000000))

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:  # reply with info for requested device

                    self.logger.debug(f"GetInfo message, replying for: {indigo.devices[devID].name}")

                    payload = {"time": time_s, "uptime": "1243200000000", "downtime": "0"}
                    replyMessage = StateInfo(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[StateInfo]:  # 35

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug(f"StateInfo message for device {devID} - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[Acknowledgement]:  # 45
            self.logger.debug("Got an ACK message.  Don't know why.")
            if message.ack_requested:
                self.logger.debug("Oops!  Client wants an ACK")
            if message.response_requested:
                self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetLocation]:  # 48

            time_s = str(int(time.time() * 1000000000))

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:  # reply with info for requested device

                    try:
                        label = indigo.devices[devID].pluginProps[ALT_NAME_KEY]
                    except (Exception,):
                        label = indigo.devices[devID].name

                    location = bytearray(base64.b64decode(indigo.devices[devID].pluginProps[LOCATION_KEY]))

                    self.logger.debug(f"GetLocation message, replying for: {indigo.devices[devID].name}")

                    payload = {"location": location, "label": label, "updated_at": time_s}
                    replyMessage = StateLocation(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[StateLocation]:  # 50

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug(f"StateLocation message for device {devID} - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[GetGroup]:  # 51

            time_s = str(int(time.time() * 1000000000))

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:  # reply with info for requested device

                    try:
                        label = indigo.devices[devID].pluginProps[ALT_NAME_KEY]
                    except (Exception,):
                        label = indigo.devices[devID].name

                    location = bytearray(base64.b64decode(indigo.devices[devID].pluginProps[LOCATION_KEY]))

                    self.logger.debug(f"GetLocation message, replying for: {indigo.devices[devID].name}")

                    payload = {"group": location, "label": label, "updated_at": time_s}
                    replyMessage = StateGroup(message.target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(message.target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[StateGroup]:  # 53

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug(f"StateGroup message for device {devID} - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[EchoRequest]:  # 58

            payload = message.payload_fields
            for devID, alias in self.publishedDevices.items():

                self.logger.debug(f"EchoRequest message, replying for: {indigo.devices[devID].name}")

                target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                replyMessage = EchoReply(target_addr, source, seq_num, payload, False, False)
                self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                if message.ack_requested:
                    replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[EchoResponse]:  # 59
            self.logger.debug("Got an EchoResponse message.  Don't know why.")
            if message.ack_requested:
                self.logger.debug("Oops!  Client wants an ACK")
            if message.response_requested:
                self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[LightGet]:  # 101

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY] or message.tagged:

                    try:
                        label = indigo.devices[devID].pluginProps[ALT_NAME_KEY]
                    except (Exception,):
                        label = indigo.devices[devID].name

                    colors = self.getDeviceColor(devID)
                    power_level = self.getDevicePower(devID)
                    self.logger.debug(f"LightGet for {indigo.devices[devID].name}, power_level = {power_level}, colors = {colors}")

                    payload = {"color": colors, "power_level": power_level, "label": label, "reserved1": "0", "reserved2": "0"}
                    target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                    replyMessage = LightState(target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[LightSetColor]:  # 102

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug(f"LightSetColor command is for device: {indigo.devices[devID].name}, payload = {message.payload_fields}")

                    for field in message.payload_fields:
                        if field[0] == "Color":
                            (hue, saturation, brightness, color) = field[1]
                            self.setDeviceColor(devID, hue, saturation, brightness, color)
                            break

                    if message.ack_requested:
                        target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    #                    if message.response_requested:
                    if True:
                        try:
                            label = indigo.devices[devID].pluginProps[ALT_NAME_KEY]
                        except (Exception,):
                            label = indigo.devices[devID].name

                        colors = self.getDeviceColor(devID)
                        power_level = self.getDevicePower(devID)
                        self.logger.debug(f"LightSetColor response power_level = {power_level}, colors = {colors}")

                        payload = {"color": colors, "power_level": power_level, "label": label, "reserved1": "0", "reserved2": "0"}
                        target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                        replyMessage = LightState(target_addr, source, seq_num, payload, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[LightState]:  # 107

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:

                    self.logger.debug(f"LightState message for device {devID} - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        elif message.message_type == MSG_IDS[LightGetPower]:  # 116

            for devID, alias in self.publishedDevices.items():

                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY] or message.tagged:

                    self.logger.debug(f"LightGetPower message, replying for: {indigo.devices[devID].name}")

                    payload = {"power_level": self.getDeviceBrightness(devID)}
                    target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                    replyMessage = LightStatePower(target_addr, source, seq_num, payload, False, False)
                    self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.ack_requested:
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[LightSetPower]:  # 117

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug(f"LightSetPower command is for device: '{indigo.devices[devID].name}', payload_fields = '{message.payload_fields}'")

                    for field in message.payload_fields:
                        if field[0] == "Power Level":
                            self.turnOnOffDevice(devID, field[1])
                            break

                    if message.ack_requested:
                        target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                        replyMessage = Acknowledgement(target_addr, source, seq_num, None, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

                    if message.response_requested:
                        payload = {"power_level": self.getDevicePower(devID)}
                        target_addr = indigo.devices[devID].pluginProps[MAC_KEY]
                        replyMessage = LightStatePower(target_addr, source, seq_num, payload, False, False)
                        self.sock.sendto(replyMessage.packed_message, (ip_addr, port))

        elif message.message_type == MSG_IDS[LightStatePower]:  # 118

            for devID, alias in self.publishedDevices.items():
                if message.target_addr == indigo.devices[devID].pluginProps[MAC_KEY]:
                    self.logger.debug(f"LightStatePower message for device {devID} - not supported!")

                    if message.ack_requested:
                        self.logger.debug("Oops!  Client wants an ACK")
                    if message.response_requested:
                        self.logger.debug("Oops!  Client wants a response")

        else:
            self.logger.debug(f"Unknown message type from {ip_addr}:{port}\n{message}")

    ########################################
    # Method called from lifxRespond() to turn on/off a device
    #
    #   deviceId is the ID of the device in Indigo
    #   turnOn is a boolean to indicate on/off
    ########################################
    def turnOnOffDevice(self, deviceId, turnOn):
        self.logger.debug(f"Set on state of device {deviceId:d} to {turnOn}")
        try:
            if turnOn:
                indigo.device.turnOn(deviceId)
            else:
                indigo.device.turnOff(deviceId)
        except (Exception,):
            self.logger.error(f"Device with id {deviceId:d} doesn't exist. The device list will be rebuilt.")
            self.refreshDeviceList()

    ########################################
    # Method called from lifxRespond() to set brightness of a device
    #
    #   deviceId is the ID of the device in Indigo
    #   brightness is in the range 0-65535 (LIFX range)
    ########################################
    def setDeviceBrightness(self, deviceId, brightness):
        try:
            iDev = indigo.devices[deviceId]
        except (Exception,):
            self.logger.error(f"Device with id {deviceId:d} doesn't exist. The device list will be rebuilt.")
            self.refreshDeviceList()
            return
        if isinstance(iDev, indigo.DimmerDevice):
            adjusted = int((brightness / 65535.0) * 100.0)  # adjust to Indigo range
            self.logger.debug(f"setDeviceBrightness: {deviceId:d} to {brightness:d}")
            indigo.dimmer.setBrightness(iDev, value=adjusted)
        else:
            self.logger.debug(f"Device with id {deviceId:d} doesn't support dimming.")

    ########################################
    # Method called from lifxRespond() to get the brightness of a device
    #
    #   deviceId is the ID of the device in Indigo
    #   brightness is in the range 0-65535 (LIFX range)
    ########################################
    def getDeviceBrightness(self, deviceId):
        try:
            iDev = indigo.devices[deviceId]
        except (Exception,):
            self.logger.error(f"Device with id {deviceId} doesn't exist. The device list will be rebuilt.")
            self.refreshDeviceList()
            return

        if isinstance(iDev, indigo.DimmerDevice):
            brightness = int((float(iDev.brightness) / 100.0) * 65535)  # adjust to LIFX range
        else:
            brightness = int(iDev.onState) * 65535
        self.logger.debug(f"getDeviceBrightness: {deviceId} is {brightness}")
        return brightness

    ########################################
    # Method called from lifxRespond() to set color of a device
    #
    #   deviceId is the ID of the device in Indigo
    #    hue, saturation, brightness are in the range 0-65535 (LIFX range)
    ########################################
    def setDeviceColor(self, deviceId, hue, saturation, brightness, color):
        self.logger.debug(f"setDeviceColor for {deviceId}: hue = {hue}, saturation = {saturation}, brightness = {brightness}, color = {color}")
        try:
            iDev = indigo.devices[deviceId]
        except (Exception,):
            self.logger.error(f"Device with id {deviceId:d} doesn't exist. The device list will be rebuilt.")
            self.refreshDeviceList()
            return

        if isinstance(iDev, indigo.DimmerDevice):
            if not iDev.supportsRGB:
                adjusted = int(round(float(brightness / 65535.0) * 100.0))  # adjust to Indigo range
                self.logger.debug(f"setDeviceColor: {deviceId:d} to {adjusted:d} (non-RGB)")
                indigo.dimmer.setBrightness(iDev, value=adjusted)
                return
            else:
                adj_hue = float(hue) / 65535.0
                adj_sat = float(saturation) / 65535.0
                adj_val = float(brightness) / 65535.0
                self.logger.debug(f"setDeviceColor adjusted: hue = {adj_hue}, saturation = {adj_sat}, brightness = {adj_val}")
                rgb_color = colorsys.hsv_to_rgb(adj_hue, adj_sat, adj_val)
                self.logger.debug(f"setDeviceColor hsv_to_rgb = {rgb_color}")
                adj_red = (rgb_color[0] * 100.0)
                adj_green = (rgb_color[1] * 100.0)
                adj_blue = (rgb_color[2] * 100.0)
                self.logger.debug(f"setColorLevels: {deviceId} to red = {adj_red}, green = {adj_green}, blue = {adj_blue}")
                indigo.dimmer.setColorLevels(iDev, adj_red, adj_green, adj_blue, 0, 0, 0)
        else:
            self.logger.debug(f"Device with id {deviceId} doesn't support dimming.")

    ########################################
    # Method called from lifxRespond() to get the color of a device
    #
    #   deviceId is the ID of the device in Indigo
    #   brightness is in the range 0-65535 (LIFX range)
    ########################################
    def getDeviceColor(self, deviceId):
        try:
            iDev = indigo.devices[deviceId]
        except (Exception,):
            self.logger.error(f"Device with id {deviceId:d} doesn't exist. The device list will be rebuilt.")
            self.refreshDeviceList()
            return

        if isinstance(iDev, indigo.DimmerDevice):
            if not iDev.supportsRGB:
                adj_hue = 0
                adj_sat = 0
                adj_val = int((iDev.brightness / 100.0) * 65535)
                temp = 3000

            else:
                red = iDev.redLevel / 100.0  # normalize first
                green = iDev.greenLevel / 100.0
                blue = iDev.blueLevel / 100.0
                hsv_color = colorsys.rgb_to_hsv(red, green, blue)

                adj_hue = int(hsv_color[0] * 65535)  # convert to LIFX
                adj_sat = int(hsv_color[1] * 65535)
                adj_val = int(hsv_color[2] * 65535)
                temp = iDev.whiteTemperature
                if not temp:
                    temp = 3000

        else:
            adj_hue = 0
            adj_sat = 0
            adj_val = int(iDev.onState * 65535)
            temp = 3000

        self.logger.debug(f"getDeviceColor of device {deviceId}: hue = {adj_hue}, sat = {adj_sat}, val = {adj_val}, temp = {temp}")
        return adj_hue, adj_sat, adj_val, temp

    ########################################
    # Method called from lifxRespond() to get the power state of a device
    #
    #   deviceId is the ID of the device in Indigo
    #   brightness is in the range 0-65535 (LIFX range)
    ########################################
    def getDevicePower(self, deviceId):
        try:
            dev = indigo.devices[deviceId]
        except (Exception,):
            self.logger.error(f"Device with id {deviceId:d} doesn't exist. The device list will be rebuilt.")
            self.refreshDeviceList()
            return
        return int(dev.onState) * 65535
