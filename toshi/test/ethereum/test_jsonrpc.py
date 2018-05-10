from toshi.test.base import AsyncHandlerTest
from toshi.handlers import BaseHandler
from toshi.ethereum import EthereumMixin
from tornado.testing import gen_test
from toshi.jsonrpc.client import JsonRPCClient
from toshi.jsonrpc.errors import JsonRPCError

from toshi.test.ethereum.parity import requires_parity, FAUCET_ADDRESS

class Handler(EthereumMixin, BaseHandler):

    async def get(self):

        balance = await self.eth.eth_getBalance(FAUCET_ADDRESS)
        self.write(str(balance))

class EthTest(AsyncHandlerTest):

    def get_urls(self):
        return [(r'^/$', Handler)]

    @gen_test
    @requires_parity
    async def test_jsonrpc_connection(self):

        resp = await self.fetch('/')
        self.assertEqual(resp.body, b'1606938044258990275541962092341162602522202993782792835301376')

    @gen_test
    @requires_parity(pass_parity=True)
    async def test_bulk(self, *, parity):
        client = JsonRPCClient(parity.dsn()['url'])

        bulk = client.bulk()
        f1 = bulk.eth_blockNumber()
        f2 = bulk.eth_getBalance(FAUCET_ADDRESS)
        f3 = bulk.eth_gasPrice()
        f4 = bulk.eth_getBalance("0x0000000000000000000000000000000000000000")
        f5 = bulk.eth_getBalance(FAUCET_ADDRESS, block=100000000)
        results = await bulk.execute()
        self.assertEqual(f1.result(), results[0])
        self.assertEqual(f2.result(), results[1])
        self.assertEqual(f3.result(), results[2])
        self.assertEqual(f4.result(), results[3])

        try:
            f5.result()
            self.fail("expected exception")
        except JsonRPCError as e:
            self.assertEqual(e.message, "Unknown block number")
        except Exception as e:
            self.fail("unexpected exception: {}".format(e))

    @gen_test
    @requires_parity(pass_parity=True)
    async def test_unknown_block_number_handling(self, *, parity):
        client = JsonRPCClient(parity.dsn()['url'])
        block_number = await client.eth_blockNumber()
        balance = await client.eth_getBalance(FAUCET_ADDRESS, block=block_number + 2)
        self.assertEqual(balance, 1606938044258990275541962092341162602522202993782792835301376)
