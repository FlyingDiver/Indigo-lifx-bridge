import SocketServer
import sys
import logging
import protocol

class LifxResponseHandler(SocketServer.BaseRequestHandler):

    def __init__(self, request, client_address, server):
        self.logger = logging.getLogger('LifxResponseHandler')
        SocketServer.BaseRequestHandler.__init__(self, request, client_address, server)
        return

#    def setup(self):
#        self.logger.debug(u"LifxResponseHandler: setup")
#        return
		
    def handle(self):
        self.logger.debug('LifxResponseHandler: handle (%s, %s)', self.request, self.client_address)
        data, socket = self.request
        self.logger.debug("LifxResponseHandler: data length: %s", len(data))

        parsed_data = protocol.parse_packet(data)
#       self.logger.debug("LifxResponseHandler: parsed_data: %s", str(parsed_data))
        return

#    def finish(self):
#        self.logger.debug(u"LifxResponseHandler: finish")
#        return
		
class LifxServer(SocketServer.UDPServer):

    def __init__(self, server_address, handler_class=LifxResponseHandler):
        self.logger = logging.getLogger('LifxServer')
        self.logger.debug(u"LifxServer: __init__")
        SocketServer.UDPServer.__init__(self, server_address, handler_class)
        return

    def server_activate(self):
        self.logger.debug(u"LifxServer: server_activate")
        SocketServer.UDPServer.server_activate(self)
        return

    def serve_forever(self):
        self.logger.debug(u"LifxServer: serve_forever")
        while True:
            self.handle_request()
        return

    def handle_request(self):
        self.logger.debug(u"LifxServer: handle_request")
        return SocketServer.UDPServer.handle_request(self)

#    def verify_request(self, request, client_address):
#        self.logger.debug('LifxServer: verify_request(%s, %s)', request, client_address)
#        return SocketServer.UDPServer.verify_request(self, request, client_address)

#    def process_request(self, request, client_address):
#        self.logger.debug('LifxServer: process_request(%s, %s)', request, client_address)
#        return SocketServer.UDPServer.process_request(self, request, client_address)

#    def finish_request(self, request, client_address):
#        self.logger.debug('LifxServer: finish_request(%s, %s)', request, client_address)
#        return SocketServer.UDPServer.finish_request(self, request, client_address)

#    def close_request(self, request_address):
#        self.logger.debug('LifxServer: close_request(%s)', request_address)
#        return SocketServer.UDPServer.close_request(self, request_address)

#    def server_close(self):
#        self.logger.debug(u"LifxServer: server_close")
#        return SocketServer.TCPServer.server_close(self)


