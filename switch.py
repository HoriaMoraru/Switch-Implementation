#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

class Switch:
    def __init__(self, switch_id, interfaces):
        self.switch_id = switch_id
        self.interfaces = interfaces
        self.cam_table = {}  # Initialize CAM table
        self.vlan_table = {}  # Initialize VLAN table

        configs_dir = "configs/"
        config_file_name = "switch" + switch_id + ".cfg"
        with open(configs_dir + config_file_name, "r") as config_file:
            self.read_switch_config(config_file)

        # Create and start a new thread that deals with sending BDPU
        self.start_bdpu_thread()

    def read_switch_config(self, config_file):
        priority = int(config_file.readline())
        for line in config_file:
            line = line.split()
            interface_name = line[0]
            interface_type = line[1]
            self.vlan_table[interface_name] = interface_type

    def start_bdpu_thread(self):
        t = threading.Thread(target=self.send_bdpu_every_sec)
        t.start()

    def send_bdpu_every_sec(self):
        while True:
            # TODO: Send BDPU every second if necessary
            time.sleep(1)

    def parse_ethernet_header(self, data):
        dest_mac = data[0:6]
        src_mac = data[6:12]
        ether_type = (data[12] << 8) + data[13]

        vlan_id = -1
        if ether_type == 0x8200:
            vlan_tci = int.from_bytes(data[14:16], byteorder='big')
            vlan_id = vlan_tci & 0x0FFF
            ether_type = (data[16] << 8) + data[17]

        return dest_mac, src_mac, ether_type, vlan_id

    def create_vlan_tag(self, vlan_id):
        return struct.pack('!H', 0x8200) + struct.pack('!H', vlan_id & 0x0FFF)

    def is_unicast(self, mac_address):
        first_byte = int(mac_address.split(":")[0], 16)
        return (first_byte & 1) == 0

    def get_interface_from_interface_name(self, interface_name):
        for i in self.interfaces:
            if get_interface_name(i) == interface_name:
                return i

    def main_loop(self):
        while True:
            interface, data, length = recv_from_any_link()
            dest_mac, src_mac, ethertype, vlan_id = self.parse_ethernet_header(data)

            dest_mac_str = ':'.join(f'{b:02x}' for b in dest_mac)
            src_mac_str = ':'.join(f'{b:02x}' for b in src_mac)

            if self.vlan_table[get_interface_name(interface)] == 'T':
                data = data[0:12] + data[16:]
            else:
                vlan_id = int(self.vlan_table[get_interface_name(interface)])

            send_interfaces = self.get_send_interfaces(vlan_id)

            self.cam_table[src_mac_str] = interface # Update CAM table

            self.handle_unicast_broadcast(interface, data, length, dest_mac_str, send_interfaces, vlan_id)

    def get_send_interfaces(self, vlan_id):
        send_interfaces = []

        for interface_vlan, interface_vlan_type in self.vlan_table.items():
            if interface_vlan_type == 'T' or int(interface_vlan_type) == vlan_id:
                send_interfaces.append(self.get_interface_from_interface_name(interface_vlan))

        return send_interfaces

    def broadcast_message(self, data, length, send_interfaces, interface, vlan_id):
        for i in send_interfaces:
            interface_name = get_interface_name(i)
            dest_vlan = self.vlan_table[interface_name]
            if i != interface:
                if dest_vlan == 'T':
                    data = data[0:12] + self.create_vlan_tag(vlan_id) + data[12:]
                    length += 4
                    send_to_link(i, data, length)
                else:
                    send_to_link(i, data, length)

    def handle_unicast_broadcast(self, interface, data, length, dest_mac_str, send_interfaces, vlan_id):
        if self.is_unicast(dest_mac_str):
            if dest_mac_str in self.cam_table:
                interface_name = get_interface_name(self.cam_table[dest_mac_str])
                dest_vlan = self.vlan_table[interface_name]
                if dest_vlan == 'T':
                    data = data[0:12] + self.create_vlan_tag(vlan_id) + data[12:]
                    length += 4
                    send_to_link(self.cam_table[dest_mac_str], data, length)
                else:
                    send_to_link(self.cam_table[dest_mac_str], data, length)
            else:
                self.broadcast_message(data, length, send_interfaces, interface, vlan_id)
        else:
            self.broadcast_message(data, length, send_interfaces, interface, vlan_id)

if __name__ == "__main__":
    switch_id = sys.argv[1]
    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)

    switch = Switch(switch_id, interfaces)
    switch.main_loop()
