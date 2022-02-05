#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# stub replacement for netifaces module so that end users don't need to install it.
#
AF_INET = 2

def interfaces():
    return ['any']

def ifaddresses(interface):
    return {AF_INET: [{'broadcast': u'255.255.255.255', 'addr': u'192.168.100.100'}]}
