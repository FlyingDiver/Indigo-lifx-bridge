# LIFX Bridge

This plugin will emulate LIFX devices for the purpose of publishing Indigo devices to be controlled by LIFX client apps.  The primary goal of this bridge was to allow control of Indigo devices by Logitech Harmony Hubs.

### Usage

The plugin is quite straight-forward: the first thing you’ll want to do is
install it. Download the version you want from the releases section above (we
always recommend the most recent release but you can go back to previous
releases if you want to). Once downloaded, double-click the plugin file in the
Finder on your Indigo Server Mac. This will install and enable the plugin. The
next sections go into more detail about configuring and using the plugin.

### Managing Devices

You need to specify the devices you want published to the bridge.  To do this, select the *Plugins-\>LIFX Bridge-\>Manage
Devices...* menu item. This will open the Manage Devices dialog.

To publish a device, select it from the *Device to publish* popup at the top.
You can specify an alternate name to publish for a device. You can use an alternate name that’s more recognized *Alternate name* field. If you’ve
already published a device, you can still select it from the top menu and change the alternate name. When you’re ready to add or update the device name, click the *Add/Update Device* button.

To unpublish a device, just select the device(s) in the *Published devices* list and click the *Delete Devices* button.

**Note**: changes made in this dialog take effect immediately - there’s no undo or save confirmations.

Once you’re finished adding/editing/deleting published devices, click the
*Close* button. 

The Configuration UI for this plugin is taken from the Alexa-Hue plugin.  Thanks for the Unlicense!


### Broadcast Messages

	PluginID: com.flyingdiver.indigoplugin.lifxbridge

 	None at this time
   
## License

This project is licensed using [Unlicense](<http://unlicense.org/>). 

