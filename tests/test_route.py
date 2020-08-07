import os
import re
import time
import json
import pytest

from swsscommon import swsscommon
from dvslib.dvs_common import PollingConfig


class TestRouteBase(object):
    def setup_db(self, dvs):
        self.pdb = dvs.get_app_db()
        self.adb = dvs.get_asic_db()
        self.cdb = dvs.get_config_db()

    def set_admin_status(self, interface, status):
        self.cdb.update_entry("PORT", interface, {"admin_status": status})
        time.sleep(1)

    def create_vrf(self, vrf_name):
        initial_entries = set(self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_VIRTUAL_ROUTER"))

        self.cdb.create_entry("VRF", vrf_name, {'empty': 'empty'})
        time.sleep(1)

        current_entries = set(self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_VIRTUAL_ROUTER"))
        assert len(current_entries - initial_entries) == 1
        return list(current_entries - initial_entries)[0]

    def remove_vrf(self, vrf_name):
        self.cdb.delete_entry("VRF", vrf_name)
        time.sleep(1)

    def create_l3_intf(self, interface, vrf_name):
        if len(vrf_name) == 0:
            self.cdb.create_entry("INTERFACE", interface, {"NULL": "NULL"})
        else:
            self.cdb.create_entry("INTERFACE", interface, {"vrf_name": vrf_name})
        time.sleep(1)

    def remove_l3_intf(self, interface):
        self.cdb.delete_entry("INTERFACE", interface)
        time.sleep(1)

    def add_ip_address(self, interface, ip):
        self.cdb.create_entry("INTERFACE", interface + "|" + ip, {"NULL": "NULL"})
        time.sleep(1)

    def remove_ip_address(self, interface, ip):
        self.cdb.delete_entry("INTERFACE", interface + "|" + ip)
        time.sleep(1)

    def create_route_entry(self, key, pairs):
        tbl = swsscommon.ProducerStateTable(self.pdb.db_connection, "ROUTE_TABLE")
        fvs = swsscommon.FieldValuePairs(list(pairs.items()))
        tbl.set(key, fvs)

    def remove_route_entry(self, key):
        tbl = swsscommon.ProducerStateTable(self.pdb.db_connection, "ROUTE_TABLE")
        tbl._del(key)

    def clear_srv_config(self, dvs):
        dvs.servers[0].runcmd("ip address flush dev eth0")
        dvs.servers[1].runcmd("ip address flush dev eth0")
        dvs.servers[2].runcmd("ip address flush dev eth0")
        dvs.servers[3].runcmd("ip address flush dev eth0")

class TestRoute(TestRouteBase):
    """ Functionality tests for route """
    def test_RouteAddRemoveIpv4Route(self, dvs, testlog):
        self.setup_db(dvs)

        self.clear_srv_config(dvs)

        # create l3 interface
        self.create_l3_intf("Ethernet0", "")
        self.create_l3_intf("Ethernet4", "")

        # set ip address
        self.add_ip_address("Ethernet0", "10.0.0.0/31")
        self.add_ip_address("Ethernet4", "10.0.0.2/31")

        # bring up interface
        self.set_admin_status("Ethernet0", "up")
        self.set_admin_status("Ethernet4", "up")

        # set ip address and default route
        dvs.servers[0].runcmd("ip address add 10.0.0.1/31 dev eth0")
        dvs.servers[0].runcmd("ip route add default via 10.0.0.0")

        dvs.servers[1].runcmd("ip address add 10.0.0.3/31 dev eth0")
        dvs.servers[1].runcmd("ip route add default via 10.0.0.2")

        # get neighbor and arp entry
        dvs.servers[0].runcmd("ping -c 1 10.0.0.3")

        # add route entry
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"ip route 2.2.2.0/24 10.0.0.1\"")
        time.sleep(1)

        # check application database
        route_entries = self.pdb.get_keys("ROUTE_TABLE")
        assert "2.2.2.0/24" in route_entries

        # check ASIC route database
        route_found = False
        for key in self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY"):
            route = json.loads(key)
            if route["dest"] == "2.2.2.0/24":
                route_found = True
        assert route_found == True

        # remove route entry
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"no ip route 2.2.2.0/24 10.0.0.1\"")
        time.sleep(1)

        # check application database
        route_entries = self.pdb.get_keys("ROUTE_TABLE")
        assert "2.2.2.0/24" not in route_entries

        # check ASIC route database
        for key in self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY"):
            route = json.loads(key)
            assert route["dest"] != "2.2.2.0/24"

        # remove ip address
        self.remove_ip_address("Ethernet0", "10.0.0.0/31")
        self.remove_ip_address("Ethernet4", "10.0.0.2/31")

        # remove l3 interface
        self.remove_l3_intf("Ethernet0")
        self.remove_l3_intf("Ethernet4")

        self.set_admin_status("Ethernet0", "down")
        self.set_admin_status("Ethernet4", "down")

        # remove ip address and default route
        dvs.servers[0].runcmd("ip route del default dev eth0")
        dvs.servers[0].runcmd("ip address del 10.0.0.1/31 dev eth0")

        dvs.servers[1].runcmd("ip route del default dev eth0")
        dvs.servers[1].runcmd("ip address del 10.0.0.3/31 dev eth0")

    def test_RouteAddRemoveIpv6Route(self, dvs, testlog):
        self.setup_db(dvs)

        # create l3 interface
        self.create_l3_intf("Ethernet0", "")
        self.create_l3_intf("Ethernet4", "")

        # bring up interface
        self.set_admin_status("Ethernet0", "up")
        self.set_admin_status("Ethernet4", "up")

        # set ip address
        self.add_ip_address("Ethernet0", "2000::1/64")
        self.add_ip_address("Ethernet4", "2001::1/64")
        dvs.runcmd("sysctl -w net.ipv6.conf.all.forwarding=1")

        # set ip address and default route
        dvs.servers[0].runcmd("ip -6 address add 2000::2/64 dev eth0")
        dvs.servers[0].runcmd("ip -6 route add default via 2000::1")

        dvs.servers[1].runcmd("ip -6 address add 2001::2/64 dev eth0")
        dvs.servers[1].runcmd("ip -6 route add default via 2001::1")
        time.sleep(2)

        # get neighbor entry
        dvs.servers[0].runcmd("ping -6 -c 1 2001::2")

        # add route entry
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"ipv6 route 3000::0/64 2000::2\"")
        time.sleep(2)

        # check application database
        route_entries = self.pdb.get_keys("ROUTE_TABLE")
        assert "3000::/64" in route_entries

        # check ASIC route database
        route_found = False
        for key in self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY"):
            route = json.loads(key)
            if route["dest"] == "3000::/64":
                route_found = True
        assert route_found == True

        # remove route entry
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"no ipv6 route 3000::0/64 2000::2\"")
        time.sleep(1)

        # check application database
        route_entries = self.pdb.get_keys("ROUTE_TABLE")
        assert "3000::/64" not in route_entries

        # check ASIC route database
        for key in self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY"):
            route = json.loads(key)
            assert route["dest"] != "3000::/64"

        # remove ip address
        self.remove_ip_address("Ethernet0", "2000::1/64")
        self.remove_ip_address("Ethernet4", "2001::1/64")

        # remove l3 interface
        self.remove_l3_intf("Ethernet0")
        self.remove_l3_intf("Ethernet4")

        self.set_admin_status("Ethernet0", "down")
        self.set_admin_status("Ethernet4", "down")

        # remove ip address and default route
        dvs.servers[0].runcmd("ip -6 route del default dev eth0")
        dvs.servers[0].runcmd("ip -6 address del 2000::2/64 dev eth0")

        dvs.servers[1].runcmd("ip -6 route del default dev eth0")
        dvs.servers[1].runcmd("ip -6 address del 2001::2/64 dev eth0")

    def test_RouteAddRemoveIpv4RouteWithVrf(self, dvs, testlog):
        self.setup_db(dvs)

        # create vrf
        vrf_1_oid = self.create_vrf("Vrf_1")
        vrf_2_oid = self.create_vrf("Vrf_2")

        # create l3 interface
        self.create_l3_intf("Ethernet0", "Vrf_1")
        self.create_l3_intf("Ethernet4", "Vrf_1")
        self.create_l3_intf("Ethernet8", "Vrf_2")
        self.create_l3_intf("Ethernet12", "Vrf_2")

        # set ip address
        self.add_ip_address("Ethernet0", "10.0.0.0/31")
        self.add_ip_address("Ethernet4", "10.0.0.2/31")
        self.add_ip_address("Ethernet8", "10.0.0.0/31")
        self.add_ip_address("Ethernet12", "10.0.0.2/31")

        # bring up interface
        self.set_admin_status("Ethernet0", "up")
        self.set_admin_status("Ethernet4", "up")
        self.set_admin_status("Ethernet8", "up")
        self.set_admin_status("Ethernet12", "up")

        # set ip address and default route
        dvs.servers[0].runcmd("ip address add 10.0.0.1/31 dev eth0")
        dvs.servers[0].runcmd("ip route add default via 10.0.0.0")

        dvs.servers[1].runcmd("ip address add 10.0.0.3/31 dev eth0")
        dvs.servers[1].runcmd("ip route add default via 10.0.0.2")

        dvs.servers[2].runcmd("ip address add 10.0.0.1/31 dev eth0")
        dvs.servers[2].runcmd("ip route add default via 10.0.0.0")

        dvs.servers[3].runcmd("ip address add 10.0.0.3/31 dev eth0")
        dvs.servers[3].runcmd("ip route add default via 10.0.0.2")

        time.sleep(1)

        # get neighbor entry
        dvs.servers[0].runcmd("ping -c 1 10.0.0.3")
        dvs.servers[2].runcmd("ping -c 1 10.0.0.3")

        # add route
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"ip route 2.2.2.0/24 10.0.0.1 vrf Vrf_1\"")
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"ip route 3.3.3.0/24 10.0.0.1 vrf Vrf_2\"")
        time.sleep(1)

        # check application database
        route_entries = self.pdb.get_keys("ROUTE_TABLE:Vrf_1")
        assert "2.2.2.0/24" in route_entries

        route_entries = self.pdb.get_keys("ROUTE_TABLE:Vrf_2")
        assert "3.3.3.0/24" in route_entries

        # check ASIC route database
        for key in self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY"):
            route = json.loads(key)
            if route["dest"] == "2.2.2.0/24" and route["vr"] == vrf_1_oid:
                route_Vrf_1_found = True
            if route["dest"] == "3.3.3.0/24" and route["vr"] == vrf_2_oid:
                route_Vrf_2_found = True
        assert route_Vrf_1_found == True and route_Vrf_2_found == True

        # remove route
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"no ip route 2.2.2.0/24 10.0.0.1 vrf Vrf_1\"")
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"no ip route 3.3.3.0/24 10.0.0.1 vrf Vrf_2\"")
        time.sleep(1)

        # check application database
        route_entries = self.pdb.get_keys("ROUTE_TABLE:Vrf_1")
        assert "2.2.2.0/24" not in route_entries

        route_entries = self.pdb.get_keys("ROUTE_TABLE:Vrf_2")
        assert "3.3.3.0/24" not in route_entries

        # check ASIC route database
        for key in self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY"):
            route = json.loads(key)
            assert route["dest"] != "2.2.2.0/24" and route["dest"] != "3.3.3.0/24"

        # remove ip address
        self.remove_ip_address("Ethernet0", "10.0.0.0/31")
        self.remove_ip_address("Ethernet4", "10.0.0.2/31")
        self.remove_ip_address("Ethernet8", "10.0.0.0/31")
        self.remove_ip_address("Ethernet12", "10.0.0.2/31")

        # remove l3 interface
        self.remove_l3_intf("Ethernet0")
        self.remove_l3_intf("Ethernet4")
        self.remove_l3_intf("Ethernet8")
        self.remove_l3_intf("Ethernet12")

        self.set_admin_status("Ethernet0", "down")
        self.set_admin_status("Ethernet4", "down")
        self.set_admin_status("Ethernet8", "down")
        self.set_admin_status("Ethernet12", "down")

        # remove vrf
        self.remove_vrf("Vrf_1")
        self.remove_vrf("Vrf_2")

        # remove ip address and default route
        dvs.servers[0].runcmd("ip route del default dev eth0")
        dvs.servers[0].runcmd("ip address del 10.0.0.1/31 dev eth0")
        dvs.servers[1].runcmd("ip route del default dev eth0")
        dvs.servers[1].runcmd("ip address del 10.0.0.3/31 dev eth0")
        dvs.servers[2].runcmd("ip route del default dev eth0")
        dvs.servers[2].runcmd("ip address del 10.0.0.1/31 dev eth0")
        dvs.servers[3].runcmd("ip route del default dev eth0")
        dvs.servers[3].runcmd("ip address del 10.0.0.3/31 dev eth0")

    def test_RouteAddRemoveIpv6RouteWithVrf(self, dvs, testlog):
        self.setup_db(dvs)

        # create vrf
        vrf_1_oid = self.create_vrf("Vrf_1")
        vrf_2_oid = self.create_vrf("Vrf_2")

        # create l3 interface
        self.create_l3_intf("Ethernet0", "Vrf_1")
        self.create_l3_intf("Ethernet4", "Vrf_1")
        self.create_l3_intf("Ethernet8", "Vrf_2")
        self.create_l3_intf("Ethernet12", "Vrf_2")

        # bring up interface
        self.set_admin_status("Ethernet0", "up")
        self.set_admin_status("Ethernet4", "up")
        self.set_admin_status("Ethernet8", "up")
        self.set_admin_status("Ethernet12", "up")

        # set ip address
        self.add_ip_address("Ethernet0", "2000::1/64")
        self.add_ip_address("Ethernet4", "2001::1/64")
        self.add_ip_address("Ethernet8", "2000::1/64")
        self.add_ip_address("Ethernet12", "2001::1/64")

        dvs.runcmd("sysctl -w net.ipv6.conf.all.forwarding=1")

        # set ip address and default route
        dvs.servers[0].runcmd("ip -6 address add 2000::2/64 dev eth0")
        dvs.servers[0].runcmd("ip -6 route add default via 2000::1")
        dvs.servers[1].runcmd("ip -6 address add 2001::2/64 dev eth0")
        dvs.servers[1].runcmd("ip -6 route add default via 2001::1")
        dvs.servers[2].runcmd("ip -6 address add 2000::2/64 dev eth0")
        dvs.servers[2].runcmd("ip -6 route add default via 2000::1")
        dvs.servers[3].runcmd("ip -6 address add 2001::2/64 dev eth0")
        dvs.servers[3].runcmd("ip -6 route add default via 2001::1")
        time.sleep(2)

        # get neighbor entry
        dvs.servers[0].runcmd("ping -6 -c 1 2001::2")
        dvs.servers[2].runcmd("ping -6 -c 1 2001::2")
        time.sleep(2)

        # add route
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"ipv6 route 3000::0/64 2000::2 vrf Vrf_1\"")
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"ipv6 route 4000::0/64 2000::2 vrf Vrf_2\"")
        time.sleep(2)

        # check application database
        route_entries = self.pdb.get_keys("ROUTE_TABLE:Vrf_1")
        assert "3000::/64" in route_entries

        route_entries = self.pdb.get_keys("ROUTE_TABLE:Vrf_2")
        assert "4000::/64" in route_entries

        # check ASIC route database
        for key in self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY"):
            route = json.loads(key)
            if route["dest"] == "3000::/64" and route["vr"] == vrf_1_oid:
                route_Vrf_1_found = True
            if route["dest"] == "4000::/64" and route["vr"] == vrf_2_oid:
                route_Vrf_2_found = True
        assert route_Vrf_1_found == True and route_Vrf_2_found == True


        # remove route
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"no ipv6 route 3000::0/64 2000::2 vrf Vrf_1\"")
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"no ipv6 route 4000::0/64 2000::2 vrf Vrf_2\"")

        # check application database
        route_entries = self.pdb.get_keys("ROUTE_TABLE:Vrf_1")
        assert "3000::/64" not in route_entries

        route_entries = self.pdb.get_keys("ROUTE_TABLE:Vrf_2")
        assert "4000::/64" not in route_entries

        # check ASIC route database
        for key in self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY"):
            route = json.loads(key)
            assert route["dest"] != "3000::/64" and route["dest"] != "4000::/64"

        # remove ip address
        self.remove_ip_address("Ethernet0", "2000::1/64")
        self.remove_ip_address("Ethernet4", "2001::1/64")
        self.remove_ip_address("Ethernet8", "2000::1/64")
        self.remove_ip_address("Ethernet12", "2001::1/64")

        # remove l3 interface
        self.remove_l3_intf("Ethernet0")
        self.remove_l3_intf("Ethernet4")
        self.remove_l3_intf("Ethernet8")
        self.remove_l3_intf("Ethernet12")

        # bring down interface
        self.set_admin_status("Ethernet0", "down")
        self.set_admin_status("Ethernet4", "down")
        self.set_admin_status("Ethernet8", "down")
        self.set_admin_status("Ethernet12", "down")

        # remove vrf
        self.remove_vrf("Vrf_1")
        self.remove_vrf("Vrf_2")

        # remove ip address and default route
        dvs.servers[0].runcmd("ip -6 route del default dev eth0")
        dvs.servers[0].runcmd("ip -6 address del 2000::2/64 dev eth0")
        dvs.servers[1].runcmd("ip -6 route del default dev eth0")
        dvs.servers[1].runcmd("ip -6 address del 2001::2/64 dev eth0")
        dvs.servers[2].runcmd("ip -6 route del default dev eth0")
        dvs.servers[2].runcmd("ip -6 address del 2000::2/64 dev eth0")
        dvs.servers[3].runcmd("ip -6 route del default dev eth0")
        dvs.servers[3].runcmd("ip -6 address del 2001::2/64 dev eth0")

    def test_RouteAndNexthopInDifferentVrf(self, dvs, testlog):
        self.setup_db(dvs)

        # create vrf
        vrf_1_oid = self.create_vrf("Vrf_1")
        vrf_2_oid = self.create_vrf("Vrf_2")

        # create l3 interface
        self.create_l3_intf("Ethernet0", "Vrf_1")
        self.create_l3_intf("Ethernet4", "Vrf_1")
        self.create_l3_intf("Ethernet8", "Vrf_2")
        self.create_l3_intf("Ethernet12", "Vrf_2")

        # set ip address
        self.add_ip_address("Ethernet0", "10.0.0.1/24")
        self.add_ip_address("Ethernet4", "10.0.1.1/24")
        self.add_ip_address("Ethernet8", "20.0.0.1/24")
        self.add_ip_address("Ethernet12", "20.0.1.1/24")

        # bring up interface
        self.set_admin_status("Ethernet0", "up")
        self.set_admin_status("Ethernet4", "up")
        self.set_admin_status("Ethernet8", "up")
        self.set_admin_status("Ethernet12", "up")

        # set ip address and default route
        dvs.servers[0].runcmd("ip address add 10.0.0.2/24 dev eth0")
        dvs.servers[0].runcmd("ip route add default via 10.0.0.1")

        dvs.servers[1].runcmd("ip address add 10.0.1.2/24 dev eth0")
        dvs.servers[1].runcmd("ip route add default via 10.0.1.1")

        dvs.servers[2].runcmd("ip address add 20.0.0.2/24 dev eth0")
        dvs.servers[2].runcmd("ip route add default via 20.0.0.1")

        dvs.servers[3].runcmd("ip address add 20.0.1.2/24 dev eth0")
        dvs.servers[3].runcmd("ip route add default via 20.0.1.1")

        time.sleep(1)

        # get neighbor entry
        dvs.servers[0].runcmd("ping -c 1 10.0.1.2")
        dvs.servers[2].runcmd("ping -c 1 20.0.1.2")

        # add route
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"ip route 20.0.1.2/32 20.0.1.2 vrf Vrf_1 nexthop-vrf Vrf_2\"")
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"ip route 10.0.0.2/32 10.0.0.2 vrf Vrf_2 nexthop-vrf Vrf_1\"")
        time.sleep(1)

        # check application database
        route_entries = self.pdb.get_keys("ROUTE_TABLE:Vrf_1")
        assert "20.0.1.2" in route_entries

        route_entries = self.pdb.get_keys("ROUTE_TABLE:Vrf_2")
        assert "10.0.0.2" in route_entries

        # check ASIC neighbor interface database
        nexthop_entries = self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_NEXT_HOP")
        for key in nexthop_entries:
            fvs = self.adb.get_entry("ASIC_STATE:SAI_OBJECT_TYPE_NEXT_HOP", key)
            status = bool(fvs)
            assert status == True
            for fv in list(fvs.items()):
                if fv[0] == "SAI_NEXT_HOP_ATTR_IP" and fv[1] == "20.0.1.2":
                    nexthop2_found = True
                    nexthop2_oid = key
                if fv[0] == "SAI_NEXT_HOP_ATTR_IP" and fv[1] == "10.0.0.2":
                    nexthop1_found = True
                    nexthop1_oid = key

        assert nexthop1_found == True and nexthop2_found == True

        # check ASIC route database
        route_entries = self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY")
        for key in route_entries:
            route = json.loads(key)
            if route["dest"] == "10.0.0.2/32" and route["vr"] == vrf_2_oid:
                fvs = self.adb.get_entry("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY", key)
                status = bool(fvs)
                assert status == True
                for fv in list(fvs.items()):
                    if fv[0] == "SAI_ROUTE_ENTRY_ATTR_NEXT_HOP_ID":
                        assert fv[1] == nexthop1_oid
                        route1_found = True
            if route["dest"] == "20.0.1.2/32" and route["vr"] == vrf_1_oid:
                fvs = self.adb.get_entry("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY", key)
                status = bool(fvs)
                assert status == True
                for fv in list(fvs.items()):
                    if fv[0] == "SAI_ROUTE_ENTRY_ATTR_NEXT_HOP_ID":
                        assert fv[1] == nexthop2_oid
                        route2_found = True
        assert route1_found == True and route2_found == True

        # Ping should work
        ping_stats = dvs.servers[0].runcmd("ping -c 1 20.0.1.2")
        assert ping_stats == 0

        # remove route
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"no ip route 20.0.1.2/32 20.0.1.2 vrf Vrf_1 nexthop-vrf Vrf_2\"")
        dvs.runcmd("vtysh -c \"configure terminal\" -c \"no ip route 10.0.0.2/32 10.0.0.2 vrf Vrf_2 nexthop-vrf Vrf_1\"")
        time.sleep(1)

        # check application database
        route_entries = self.pdb.get_keys("ROUTE_TABLE:Vrf_1")
        assert "20.0.1.2" not in route_entries

        route_entries = self.pdb.get_keys("ROUTE_TABLE:Vrf_2")
        assert "10.0.0.2" not in route_entries

        # check ASIC route database
        for key in self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY"):
            route = json.loads(key)
            assert route["dest"] != "10.0.0.2/32" and route["dest"] != "20.0.1.2/32"

        # remove ip address
        self.remove_ip_address("Ethernet0", "10.0.0.1/24")
        self.remove_ip_address("Ethernet4", "10.0.1.1/24")
        self.remove_ip_address("Ethernet8", "20.0.0.1/24")
        self.remove_ip_address("Ethernet12", "20.0.1.1/24")

        # remove l3 interface
        self.remove_l3_intf("Ethernet0")
        self.remove_l3_intf("Ethernet4")
        self.remove_l3_intf("Ethernet8")
        self.remove_l3_intf("Ethernet12")

        self.set_admin_status("Ethernet0", "down")
        self.set_admin_status("Ethernet4", "down")
        self.set_admin_status("Ethernet8", "down")
        self.set_admin_status("Ethernet12", "down")

        # remove vrf
        self.remove_vrf("Vrf_1")
        self.remove_vrf("Vrf_2")

        # remove ip address and default route
        dvs.servers[0].runcmd("ip route del default dev eth0")
        dvs.servers[0].runcmd("ip address del 10.0.0.2/24 dev eth0")
        dvs.servers[1].runcmd("ip route del default dev eth0")
        dvs.servers[1].runcmd("ip address del 10.0.1.2/24 dev eth0")
        dvs.servers[2].runcmd("ip route del default dev eth0")
        dvs.servers[2].runcmd("ip address del 20.0.0.2/24 dev eth0")
        dvs.servers[3].runcmd("ip route del default dev eth0")
        dvs.servers[3].runcmd("ip address del 20.0.1.2/24 dev eth0")

class TestRoutePerf(TestRouteBase):
    """ Performance tests for route """
    def test_PerfAddRemoveRoute(self, dvs, testlog):
        self.setup_db(dvs)
        self.clear_srv_config(dvs)
        numRoutes = 10000   # number of routes to add/remove
        timeout = 30        # timeout if routes are not successfully added/removed in 30 seconds

        # generate addresses of routes
        addrs = []
        for i in range(numRoutes):
            addrs.append("%d.%d.%d.%d/%d" % (100 + int(i / 256 ** 2), int(i / 256), i % 256, 0, 24))

        # create l3 interface
        self.create_l3_intf("Ethernet0", "")
        self.create_l3_intf("Ethernet4", "")

        # set ip address
        self.add_ip_address("Ethernet0", "10.0.0.0/31")
        self.add_ip_address("Ethernet4", "10.0.0.2/31")

        # bring up interface
        self.set_admin_status("Ethernet0", "up")
        self.set_admin_status("Ethernet4", "up")

        # set ip address and default route
        dvs.servers[0].runcmd("ip address add 10.0.0.1/31 dev eth0")
        dvs.servers[0].runcmd("ip route add default via 10.0.0.0")

        dvs.servers[1].runcmd("ip address add 10.0.0.3/31 dev eth0")
        dvs.servers[1].runcmd("ip route add default via 10.0.0.2")

        fieldValues = [{"nexthop": "10.0.0.1", "ifname": "Ethernet0"}, {"nexthop": "10.0.0.3", "ifname": "Ethernet4"}]

        # get neighbor and arp entry
        dvs.servers[0].runcmd("ping -c 1 10.0.0.3")

        # get number of routes before adding new routes
        startNumRoutes = len(self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY"))

        # add route entries
        timeStart = time.time()
        for i in range(numRoutes):
            self.create_route_entry(addrs[i], fieldValues[i % 2])

        # wait until all routes are added into ASIC database
        pollingCfg = PollingConfig(polling_interval=0.01, timeout=timeout, strict=True) # extend timeout since routes may take longer than 5 seconds (default timeout) to load
        self.adb.wait_for_n_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY", startNumRoutes + numRoutes, pollingCfg)
        print("Time to add %d routes is %.2f seconds. " % (numRoutes, time.time() - timeStart))

        # confirm all routes are added
        asicAddrs = set()
        for key in self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY"):
            route = json.loads(key)
            asicAddrs.add(route["dest"])
        for addr in addrs:
            assert addr in asicAddrs

        #remove route entries
        timeStart = time.time()
        for i in range(numRoutes):
            self.remove_route_entry(addrs[i])

        # wait until all routes are removed from ASIC database
        self.adb.wait_for_n_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY", startNumRoutes, pollingCfg)
        print("Time to remove %d routes is %.2f seconds. " % (numRoutes, time.time() - timeStart))

        # confirm all routes are removed
        asicAddrs = set()
        for key in self.adb.get_keys("ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY"):
            route = json.loads(key)
            asicAddrs.add(route["dest"])
        for addr in addrs:
            assert not addr in asicAddrs

        # remove ip address
        self.remove_ip_address("Ethernet0", "10.0.0.0/31")
        self.remove_ip_address("Ethernet4", "10.0.0.2/31")

        # remove l3 interface
        self.remove_l3_intf("Ethernet0")
        self.remove_l3_intf("Ethernet4")

        self.set_admin_status("Ethernet0", "down")
        self.set_admin_status("Ethernet4", "down")

        # remove ip address and default route
        dvs.servers[0].runcmd("ip route del default dev eth0")
        dvs.servers[0].runcmd("ip address del 10.0.0.1/31 dev eth0")

        dvs.servers[1].runcmd("ip route del default dev eth0")
        dvs.servers[1].runcmd("ip address del 10.0.0.3/31 dev eth0")
