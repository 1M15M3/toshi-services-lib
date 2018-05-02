import asyncio
import binascii
import random
import regex
import tornado.httpclient
import logging

from toshi.jsonrpc.errors import JsonRPCError
from toshi.utils import parse_int

JSONRPC_LOG = logging.getLogger("toshi.jsonrpc.client")

JSON_RPC_VERSION = "2.0"

HEX_RE = regex.compile("(0x)?([0-9a-fA-F]+)")

def validate_hex(value, length=None):
    if isinstance(value, int):
        if value < 0:
            raise ValueError("Negative values are unsupported")
        value = hex(value)[2:]
    if isinstance(value, bytes):
        value = binascii.b2a_hex(value).decode('ascii')
    else:
        m = HEX_RE.match(value)
        if m:
            value = m.group(2)
        else:
            raise ValueError("Unable to convert value to valid hex string")
    if length:
        if len(value) > length * 2:
            raise ValueError("Value is too long")
        return '0x' + value.rjust(length * 2, '0')
    return '0x' + value

def validate_block_param(param):

    if param not in ("earliest", "latest", "pending"):
        return validate_hex(param)
    return param

class JsonRPCClient:

    def __init__(self, url, should_retry=True, log=None, max_clients=100, bulk_mode=False):
        self._url = url
        self._max_clients = max_clients
        self._httpclient = tornado.httpclient.AsyncHTTPClient(max_clients=self._max_clients)
        if log is None:
            self.log = JSONRPC_LOG
        else:
            self.log = log
        self.should_retry = should_retry
        self._bulk_mode = bulk_mode
        self._bulk_futures = {}
        self._bulk_data = []

    def _fetch(self, method, params=None, result_processor=None):
        id = random.randint(0, 1000000)

        if params is None:
            params = []

        data = {
            "jsonrpc": JSON_RPC_VERSION,
            "id": id,
            "method": method,
            "params": params
        }

        if self._bulk_mode is True:
            while id in self._bulk_futures:
                id = random.randint(0, 1000000)
                data['id'] = id
            self._bulk_data.append(data)
            future = asyncio.get_event_loop().create_future()
            self._bulk_futures[id] = (future, result_processor)
            return future

        return self._execute_single(data, result_processor)

    async def _execute_single(self, data, result_processor):
        # NOTE: letting errors fall through here for now as it means
        # there is something drastically wrong with the jsonrpc server
        # which means something probably needs to be fixed
        retries = 0
        while True:
            try:
                resp = await self._httpclient.fetch(
                    self._url,
                    method="POST",
                    headers={'Content-Type': "application/json"},
                    body=tornado.escape.json_encode(data)
                )
            except:
                self.log.error("Error in JsonRPCClient._fetch ({}): retry {}".format(data['method'], retries))
                retries += 1
                # give up after a "while"
                if not self.should_retry or retries >= 5:
                    raise
                await asyncio.sleep(0.5)
            else:
                break

        rval = tornado.escape.json_decode(resp.body)

        # verify the id we got back is the same as what we passed
        if data['id'] != rval['id']:
            raise JsonRPCError(-1, "returned id was not the same as the inital request")

        if "error" in rval:
            raise JsonRPCError(rval['id'], rval['error']['code'], rval['error']['message'], rval['error']['data'] if 'data' in rval['error'] else None)

        if result_processor:
            return result_processor(rval['result'])
        return rval['result']

    def eth_getBalance(self, address, block="latest"):

        address = validate_hex(address)
        block = validate_block_param(block)

        return self._fetch("eth_getBalance", [address, block], parse_int)

    def eth_getTransactionCount(self, address, block="latest"):

        address = validate_hex(address)
        block = validate_block_param(block)

        return self._fetch("eth_getTransactionCount", [address, block], parse_int)

    def eth_estimateGas(self, source_address, target_address, **kwargs):

        source_address = validate_hex(source_address)
        hexkwargs = {"from": source_address}

        if target_address:
            target_address = validate_hex(target_address)
            hexkwargs["to"] = target_address

        for k, value in kwargs.items():
            if k == 'gasprice' or k == 'gas_price':
                k = 'gasPrice'
            hexkwargs[k] = validate_hex(value)
        if 'value' not in hexkwargs:
            hexkwargs['value'] = "0x0"
        return self._fetch("eth_estimateGas", [hexkwargs], parse_int)

    def eth_sendRawTransaction(self, tx):

        tx = validate_hex(tx)
        return self._fetch("eth_sendRawTransaction", [tx])

    def eth_getTransactionReceipt(self, tx):

        tx = validate_hex(tx)
        return self._fetch("eth_getTransactionReceipt", [tx])

    def eth_getTransactionByHash(self, tx):

        tx = validate_hex(tx)
        return self._fetch("eth_getTransactionByHash", [tx])

    def eth_blockNumber(self):

        return self._fetch("eth_blockNumber", [], parse_int)

    def eth_getBlockByNumber(self, number, with_transactions=True):

        number = validate_block_param(number)

        return self._fetch("eth_getBlockByNumber", [number, with_transactions])

    def eth_newFilter(self, *, fromBlock=None, toBlock=None, address=None, topics=None):

        kwargs = {}
        if fromBlock:
            kwargs['fromBlock'] = validate_block_param(fromBlock)
        if toBlock:
            kwargs['toBlock'] = validate_block_param(toBlock)
        if address:
            kwargs['address'] = validate_hex(address)
        if topics:
            if not isinstance(topics, list):
                raise TypeError("topics must be an array of DATA")
            kwargs['topics'] = [None if i is None else validate_hex(i, 32) for i in topics]

        return self._fetch("eth_newFilter", [kwargs])

    def eth_newPendingTransactionFilter(self):

        return self._fetch("eth_newPendingTransactionFilter", [])

    def eth_newBlockFilter(self):

        return self._fetch("eth_newBlockFilter", [])

    def eth_getFilterChanges(self, filter_id):

        return self._fetch("eth_getFilterChanges", [filter_id])

    def eth_getFilterLogs(self, filter_id):

        return self._fetch("eth_getFilterLogs", [filter_id])

    def eth_uninstallFilter(self, filter_id):

        return self._fetch("eth_uninstallFilter", [filter_id])

    def eth_getCode(self, address, block="latest"):

        address = validate_hex(address)
        block = validate_block_param(block)
        return self._fetch("eth_getCode", [address, block])

    def eth_getLogs(self, fromBlock=None, toBlock=None, address=None, topics=None):

        kwargs = {}
        if fromBlock:
            kwargs['fromBlock'] = validate_block_param(fromBlock)
        if toBlock:
            kwargs['toBlock'] = validate_block_param(toBlock)
        if address:
            kwargs['address'] = validate_hex(address)
        if topics:
            # validate topics
            if not isinstance(topics, list):
                raise TypeError("topics must be an array of DATA")
            for topic in topics:
                if isinstance(topic, list):
                    if not all(validate_hex(t, 32) for t in topic):
                        raise TypeError("topics must be an array of DATA")
                else:
                    if not validate_hex(topic):
                        raise TypeError("topics must be an array of DATA")
            kwargs['topics'] = topics

        return self._fetch("eth_getLogs", [kwargs])

    def eth_call(self, *, to_address, from_address=None, gas=None, gasprice=None, value=None, data=None, block="latest"):

        to_address = validate_hex(to_address)
        block = validate_block_param(block)

        callobj = {"to": to_address}
        if from_address:
            callobj['from'] = validate_hex(from_address)
        if gas:
            callobj['gas'] = validate_hex(gas)
        if gasprice:
            callobj['gasPrice'] = validate_hex(gasprice)
        if value:
            callobj['value'] = validate_hex(value)
        if data:
            callobj['data'] = validate_hex(data)

        return self._fetch("eth_call", [callobj, block])

    def eth_gasPrice(self):

        return self._fetch("eth_gasPrice", [], parse_int)

    def trace_transaction(self, transaction_hash):

        return self._fetch("trace_transaction", [transaction_hash])

    def trace_get(self, transaction_hash, *positions):

        return self._fetch("trace_get", [transaction_hash, positions])

    def trace_replayTransaction(self, transaction_hash, *, vmTrace=False, trace=True, stateDiff=False):

        trace_type = []
        if vmTrace:
            trace_type.append('vmTrace')
        if trace:
            trace_type.append('trace')
        if stateDiff:
            trace_type.append('stateDiff')

        return self._fetch("trace_replayTransaction", [transaction_hash, trace_type])

    def debug_traceTransaction(self, transaction_hash, *, disableStorage=None, disableMemory=None, disableStack=None,
                               fullStorage=None, tracer=None, timeout=None):
        kwargs = {}
        if disableStorage is not None:
            kwargs['disableStorage'] = disableStorage
        if disableMemory is not None:
            kwargs['disableMemory'] = disableMemory
        if disableStack is not None:
            kwargs['disableStack'] = disableStack
        if tracer is not None:
            kwargs['tracer'] = tracer
        if timeout is not None:
            kwargs['timeout'] = str(timeout)

        return self._fetch("debug_traceTransaction", [transaction_hash, kwargs])

    def web3_clientVersion(self):

        return self._fetch("web3_clientVersion", [])

    def net_version(self):

        return self._fetch("net_version", [])

    def bulk(self):
        return JsonRPCClient(self._url, self.should_retry, self.log, max_clients=self._max_clients, bulk_mode=True)

    async def execute(self):
        if not self._bulk_mode:
            raise Exception("No Bulk request started")
        if len(self._bulk_data) == 0:
            return []

        data = self._bulk_data[:]
        self._bulk_data = []
        futures = self._bulk_futures.copy()
        self._bulk_futures = {}

        retries = 0
        while True:
            try:
                resp = await self._httpclient.fetch(
                    self._url,
                    method="POST",
                    headers={'Content-Type': "application/json"},
                    body=tornado.escape.json_encode(data)
                )
            except:
                self.log.error("Error in JsonRPCClient.execute: retry {}".format(retries))
                retries += 1
                # give up after a "while"
                if not self.should_retry or retries >= 5:
                    raise
                await asyncio.sleep(0.5)
            else:
                break

        rvals = tornado.escape.json_decode(resp.body)

        results = []
        for rval in rvals:
            if 'id' not in rval:
                continue
            future, result_processor = futures.pop(rval['id'], (None, None))
            if future is None:
                self.log.warning("Got unexpected id in jsonrpc bulk response")
                continue
            if "error" in rval:
                future.set_exception(JsonRPCError(rval['id'], rval['error']['code'], rval['error']['message'], rval['error']['data'] if 'data' in rval['error'] else None))
                result = None
            else:
                if result_processor:
                    result = result_processor(rval['result'])
                else:
                    result = rval['result']
                future.set_result(result)
            results.append(result)

        if len(futures):
            self.log.warning("Found some unprocessed requests in bulk jsonrpc request")
            for future, result_processor in futures:
                future.set_exception(Exception("Unexpectedly missing result"))

        return results
