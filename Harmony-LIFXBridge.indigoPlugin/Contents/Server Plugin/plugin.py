#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import socket
import threading
from responder import LifxResponseHandler, LifxServer

try:
    import indigo
except:
    pass

# Note the "indigo" module is automatically imported and made available inside
# our global name space by the host process. We add it here so that the various
# Python IDEs will not show errors on each usage of the indigo module.

PUBLISHED_KEY = "published"
ALT_NAME_KEY = "alternate-name"
DEFAULT_LIFX_PORT = 56700


################################################################################
class Plugin(indigo.PluginBase):
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        
        self.debug = self.pluginPrefs.get("showDebugInfo", False)
        self.debugLog(u"Debugging enabled")
                    
        self.server = None
        
        self.refreshDeviceList()
        
        # Need to subscribe to device changes here so we can call the refreshDeviceList method
        # in case there was a change or deletion of a device that's published
        indigo.devices.subscribeToChanges()

    def __del__(self):
        indigo.PluginBase.__del__(self)

    def startup(self):
        indigo.server.log(u"Starting Harmony Hub bridge server thread")

    	address = ('', DEFAULT_LIFX_PORT)
    	self.server = LifxServer(address, LifxResponseHandler)
    	ip, port = self.server.server_address
    	self.debugLog('Server on ' +  str(ip) + ':' + str(port))

    	t = threading.Thread(target=self.server.serve_forever)
    	t.setDaemon(True) # don't hang on exit
    	t.start()

    def shutdown(self):
        self.debugLog(u"Shutting down Harmony Hub bridge server")
        if self.server:
    		self.server.socket.close()


    ########################################
    # Prefs dialog methods
    ########################################
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        # Since the dialog closed we want to set the debug flag - if you don't directly use
        # a plugin's properties (and for debugLog we don't) you'll want to translate it to
        # the appropriate stuff here.
        if not userCancelled:
            self.debug = valuesDict.get("showDebugInfo", False)
            if self.debug:
                indigo.server.log(u"Debug logging enabled")
            else:
                indigo.server.log(u"Debug logging disabled")
            self.threadDebug = valuesDict.get("showThreadDebugInfo", False)
            if self.threadDebug:
                indigo.server.log(u"Thread debug logging enabled")
            else:
                indigo.server.log(u"Thread debug logging disabled")

    ########################################
    # The next two methods should catch when a device name changes in Indigo and when a device we have published
    # gets deleted - we'll just rebuild the device list cache in those situations.
    ########################################
    def deviceDeleted(self, dev):
        self.debugLog(u"deviceDeleted called")
        if dev.id in self.publishedDevices:
            indigo.server.log(u"A device (%s) that was published has been deleted." % dev.name)
            self.refreshDeviceList()

    def deviceUpdated(self, origDev, newDev):
        #self.debugLog(u"deviceUpdated called with id: %i" % origDev.id)
        if origDev.id in self.publishedDevices:
            # Drill down on the change a bit - if the name changed and there's no alternate name OR the alternate
            # name changed then refresh the device list
            if ALT_NAME_KEY in origDev.pluginProps or ALT_NAME_KEY in newDev.pluginProps:
                if origDev.pluginProps.get(ALT_NAME_KEY, None) != newDev.pluginProps.get(ALT_NAME_KEY, None):
                    self.refreshDeviceList()
                    indigo.server.log(u"A device alternative name changed.")
            elif origDev.name != newDev.name:
                self.refreshDeviceList()
                indigo.server.log(u"A device name changed.")
            elif origDev.pluginProps.get(PUBLISHED_KEY, "False") != newDev.pluginProps.get(PUBLISHED_KEY, "False"):
                self.refreshDeviceList()
                indigo.server.log(u"Your published device list changed.")

    ########################################
    # This method is called to refresh the list of published devices.
    ########################################
    def refreshDeviceList(self):
        self.debugLog(u"refreshDeviceList called")
        self.publishedDevices = dict()
        for dev in indigo.devices:
            props = dev.pluginProps
            if PUBLISHED_KEY in props:
                self.debugLog(u"found published device: %i - %s" % (dev.id, dev.name))
                self.publishedDevices[dev.id] = props.get(ALT_NAME_KEY, "")
        indigo.server.log(u"%i devices published" % len(self.publishedDevices))

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
        self.debugLog(u"selectDeviceToAdd called")
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
        self.debugLog(u"addDevice called")
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
        self.debugLog(u"adding device: %s" % deviceId)
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
        self.debugLog(u"addDevice: valuesDict['altName']: |%s|" % str(valuesDict["altName"]))
        if len(valuesDict["altName"]):
            props[ALT_NAME_KEY] = valuesDict["altName"]
        elif ALT_NAME_KEY in props:
            del props[ALT_NAME_KEY]
        # Replace the props on the server's copy of the device instance.
        dev.replacePluginPropsOnServer(props)
        self.debugLog(u"valuesDict = " + str(valuesDict))
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
        self.debugLog(u"deleteDevices called")
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
        self.debugLog(u"memberDevices called with filter: %s  typeId: %s  targetId: %s" % (filter, typeId, str(targetId)))
        returnList = list()
        for id, name in self.publishedDevices.items():
            deviceName = indigo.devices[id].name
            if len(name) > 0:
                deviceName += " (%s)" % name
            returnList.append((id, deviceName))
            returnList = sorted(returnList, key= lambda item: item[1])
        return returnList

    ########################################
    # This is the method that's called to build the member device list. Note
    # that valuesDict is read-only so any changes you make to it will be discarded.
    ########################################
    def getHueDeviceJSON(self, deviceId=None):
        try:
            if deviceId:
                # Return the JSON for a single device
                self.debugLog(u"getHueDeviceJSON called with device ID: %i" % deviceId)
                deviceDict = self._createDeviceDict(indigo.devices[deviceId])
                self.debugLog(u"json: \n%s" % json.dumps(deviceDict, indent=4))
                return json.dumps(deviceDict)
            else:
                # Return the JSON for all devices - called when discovering devices
                self.debugLog(u"getHueDeviceJSON called for all devices")
                deviceListDict = self._createFullDeviceDict()
                self.debugLog('deviceListDict: %s' % str(deviceListDict))
                self.debugLog(u"json: \n%s" % json.dumps(deviceListDict, indent=4))
                return json.dumps(deviceListDict)
        except Exception, e:
            self.errorLog(u"getHueDeviceJSON exception: \n%s" % str(traceback.format_exc(10)))

    ################################################################################
    # Utility methods to create the Hue dicts that will be converted to JSON
    ################################################################################
    def _createDeviceDict(self, devId):
        self.debugLog(u"_createDeviceDict called")
        dev = indigo.devices[devId]
        brightness = dev.states.get("brightness", 255)
        name = dev.name
        if ALT_NAME_KEY in dev.pluginProps:
            name = dev.pluginProps[ALT_NAME_KEY]
        return {
            "pointsymbol": {
                "1": "none",
                "3": "none",
                "2": "none",
                "5": "none",
                "4": "none",
                "7": "none",
                "6": "none",
                "8": "none",
            },
            "state": {
                "on": dev.onState,
                "xy": [0.4589, 0.4103],
                "alert": "none",
                "reachable": dev.enabled,
                "bri": brightness,
                "hue": 14924,
                "colormode": "hs",
                "ct": 365,
                "effect": "none",
                "sat": 143
            },
            "swversion": "6601820",
            "name": name.encode('ascii', 'ignore'),
            "manufacturername": "Philips",
            "uniqueid": str(dev.id),
            "type": "Extended color light",
            "modelid": "LCT001"
        }

    def _createFullDeviceDict(self):
        self.debugLog(u"_createFullDeviceDict called")
        returnDict = dict()
        for devId in self.publishedDevices.keys():
            newDeviceDict = self._createDeviceDict(devId)
            self.debugLog(u"_createFullDeviceDict: new device added: \n%s" % str(newDeviceDict))
            returnDict[str(devId)] = newDeviceDict
        return returnDict

    ########################################
    # Method called from bridge thread to turn on/off a device
    #
    #   deviceId is the ID of the device in Indigo
    #   turnOn is a boolean to indicate on/off
    ########################################
    def turnOnOffDevice(self, deviceId, turnOn):
        indigo.server.log(u"Set on state of device %i to %s" % (deviceId, str(turnOn)))
        try:
            if turnOn:
                indigo.device.turnOn(deviceId)
            else:
                indigo.device.turnOff(deviceId)
        except:
            self.errorLog(u"Device with id %i doesn't exist. The device list will be rebuilt - you should rerun discovery on your Alexa-compatible device." % deviceId)
            self.refreshDeviceList()

    ########################################
    # Method called from bridge thread to set brightness of a device
    #
    #   deviceId is the ID of the device in Indigo
    #   brightness is the brightness in the range 0-100
    ########################################
    def setDeviceBrightness(self, deviceId, brightness):
        try:
            dev = indigo.devices[deviceId]
        except:
            self.errorLog(u"Device with id %i doesn't exist. The device list will be rebuilt - you should rerun discovery on your Alexa-compatible device." % deviceId)
            self.refreshDeviceList()
            return
        if isinstance(dev, indigo.DimmerDevice):
            indigo.server.log(u"Set brightness of device %i to %i" % (deviceId, brightness))
            indigo.dimmer.setBrightness(dev, value=brightness)
        else:
            self.errorLog(u"Device with id %i doesn't support dimming." % deviceId)

    ########################################
    # Actions defined in MenuItems.xml:
    ########################################
    def toggleDebugging(self):
        if self.debug:
            indigo.server.log(u"Turning off debug logging")
            self.pluginPrefs["showDebugInfo"] = False
        else:
            indigo.server.log(u"Turning on debug logging")
            self.pluginPrefs["showDebugInfo"] = True
        self.debug = not self.debug
