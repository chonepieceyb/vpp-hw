from framework import VppTestCase, ppp
from scapy.layers.l2 import Ether
from scapy.packet import Raw
from scapy.layers import inet
import time

class TestBatchTimeout(VppTestCase):
    """test vpp batch + timeout"""

    @classmethod
    def setUpClass(cls):
        super(TestBatchTimeout, cls).setUpClass()
        try:
            cls.create_pg_interfaces(range(2))
            for i in cls.pg_interfaces:
                i.admin_up()
                i.config_ip4()
                i.resolve_arp()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        for i in cls.pg_interfaces:
            i.unconfig_ip4()
            i.admin_down()
        super(TestBatchTimeout, cls).tearDownClass()

    def create_stream(self, src_if, dst_if, count):
        packets = []
        for i in range(count):
            info = self.create_packet_info(src_if, dst_if)
            payload = self.info_to_payload(info)
            p = (
                Ether(dst=src_if.local_mac, src=src_if.remote_mac)
                / inet.IP(src=src_if.remote_ip4, dst=dst_if.remote_ip4)
                / inet.UDP(sport=6666, dport=6666)
                / Raw(payload)
            )
            info.data = p.copy()
            packets.append(p)
        
        return packets

    def verify_capture(self, src_if, dst_if, capture):
        packet_info = None
        
        for packet in capture:
            try: 
                ip = packet[inet.IP]
                udp = packet[inet.UDP]
                # convert the payload to packet info object
                payload_info = self.payload_to_info(packet[Raw])
                # make sure the indexes match
                self.assert_equal(
                    payload_info.src, src_if.sw_if_index, "source sw_if_index"
                )
                self.assert_equal(
                    payload_info.dst, dst_if.sw_if_index, "destination sw_if_index"
                )
                packet_info = self.get_next_packet_info_for_interface2(
                    src_if.sw_if_index, dst_if.sw_if_index, packet_info
                )
                # make sure we didn't run out of saved packets
                self.assertIsNotNone(packet_info)
                self.assert_equal(
                    payload_info.index, packet_info.index, "packet info index"
                )
                saved_packet = packet_info.data  # fetch the saved packet
                # assert the values match
                self.assert_equal(ip.src, saved_packet[inet.IP].src, "IP source address")
                # ... more assertions here
                self.assert_equal(udp.sport, saved_packet[inet.UDP].sport, "UDP source port")
                
            except Exception:
                self.logger.error(ppp("Unexpected or invalid packet:", packet))
                raise
         
        remaining_packet = self.get_next_packet_info_for_interface2(
            src_if.sw_if_index, dst_if.sw_if_index, packet_info
        )
        self.assertIsNone(
            remaining_packet,
            "Interface %s: Packet expected from interface "
            "%s didn't arrive" % (dst_if.name, src_if.name),
        )

    def test_batch_timeout(self):
        # self.vapi.cli("set buffer traces on")

        # reply = self.vapi.cli("show buffer traces status")
        # self.assertIn("buffers tracing is on", reply)

        packets = self.create_stream(self.pg0, self.pg1, 63)
        self.pg0.add_stream(packets)
        self.pg0.enable_capture()
        self.pg1.enable_capture()
        self.pg_start()
        
        capture = self.pg1.get_capture()
        self.pg0.assert_nothing_captured()
        self.verify_capture(self.pg0, self.pg1, capture)
        time.sleep(10)
        # expected = [
        #     "ip4-rewrite",
        # ]
        reply = self.vapi.cli("show runtime")
        # for entry in expected:
        #     self.assertIn(entry, reply)

        self.assertIn("Avg DPC", reply)
        self.assertIn("Total DTO", reply)

        self.logger.info(reply)


if __name__ == "__main__":
    unittest.main(testRunner=VppTestRunner)