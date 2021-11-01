# -*- coding: utf-8 -*-
"""
Created on Wed Oct 27 19:05:21 2021

@author: andrew
"""

from hashlib import sha256
import copy
import json

class Hashable:
    @staticmethod
    def hash_fn(string): return sha256(string.encode('utf-8')).hexdigest()[:8]
    
    def hash(self): return Hashable.hash_fn(self.__str__())

# Account is main piece of state in Etheurem
# regular externally owned account holds balance (just like Bitcoin account)
# keyi also have Contract account that also holds code and data storage
class Account(Hashable):    
    EXTERNALLY_OWNED = 'externally_owned'
    CONTRACT = 'contract'
    
    # nonce = counter used to make sure ea transac only processed once
    # balance = account's curr ether balance
    # code = contract code (if present)
    # storage = empty be default
    def __init__(self, address, nonce, balance, code=None, storage={}, creation_tx_hash=None):
        self.address = address
        self.nonce = nonce
        self.balance = balance
        self.code = code
        self.storage = storage
        self.creation_tx_hash = creation_tx_hash
        
    def type(self):
        return self.EXTERNALLY_OWNED if self.code is None else self.CONTRACT
        
    # ability to hash into 8 char string 
    def __str__(self):
        ret = 'Contract' if self.type() == self.CONTRACT else ''
        return ret + 'Account: {0}\nNonce: {1}, Balance: {2}\nCode: {3}\nStorage: {4}\n'.format(self.address, self.nonce, self.balance, self.code, self.storage)

    def call_contract(self, args):
        exec(self.code, {'storage': self.storage, 'args': args})
        
# state of the entire world = set of Accounts
class WorldState(Hashable):
    def __init__(self, accounts):
        self.accounts = accounts
        
    def __str__(self):
        return '\n'.join([account.__str__() for account in self.accounts.values()])
        
    def signature(self):
        return self.__str__()
        
    def account_created_by_tx_hash(self, creation_tx_hash):
        return next((a for a in self.accounts.values() if a.creation_tx_hash == creation_tx_hash), None)
    

# Block = bunch of transacs + ptr to prev block
class Block(Hashable):
    def __init__(self, transactions, prev_block_hash, end_state_signature):
        self.prev_block_hash = prev_block_hash
        self.transactions = transactions
        self.end_state_signature = end_state_signature
        
    def __str__(self):
        stringified_txs = '\t'.join([tx.__str__() for tx in self.transactions.values()])
        return '{0}\t{1}\t{2}'.format(self.prev_block_hash, self.end_state_signature, stringified_txs)
        
# Transaction = "do something" in Ethereum
#   transfer ether, create accnts (incl. contract accnt), call contract accnts (call contract code and pass some data)

# 5 fields
# 1. address of sender account
# 2. address of receiver account
# 3. nonce that must match nonce in sender accnt
    # idempotency key to ensure same transac isnt sent twice
# 4. amount of ether to send from sender to receiver
# (optional) 5. data field 
    # in contract creation, this is the str containing contract code
    # in contract call, this is JSON arg thats passed down to contract code
    
# ea Transac changes the world state S via apply_transaction(S, TX) -> S
class Transaction(Hashable):
    def __init__(self, sender_addr, receiver_addr, nonce, amount, data):
        self.sender_addr = sender_addr
        self.receiver_addr = receiver_addr
        self.amount = amount
        self.data = data
        self.nonce = nonce

    def __str__(self):
        return '{0},{1},{2},{3}'.format(self.sender_addr, self.receiver_addr, self.amount, self.data)
        

# 0xDEADBEEF is used as debug val
ROOT_ACCOUNT_ADDR = 'deadbeef'
class BlockChain(Hashable):
    PRE_GENESIS_BLOCK_HASH= '00000000'
    def genesis_block(self):
        return Block({}, self.PRE_GENESIS_BLOCK_HASH, self.genesis_world_state().signature())
        
    def genesis_world_state(self):
        return WorldState({ROOT_ACCOUNT_ADDR: Account(ROOT_ACCOUNT_ADDR, 0, 1000)})
        
    ## Toplevel Blockchain API
    def __init__(self):
        self.blocks = {self.genesis_block().hash(): self.genesis_block()}
        self.tx_queue = {}
        
    def enqueue_transaction(self, tx):
        self.tx_queue[tx.hash()] = tx
        
    def mine_new_block(self):
        # first create fake block (used to calc the end state signature)
        block_without_end_state_sig = Block(self.tx_queue, self.last_block().hash(), 'REPLACE_ME')
        sig = self.end_state_signature(block_without_end_state_sig)
        
        # now we have end state sig --> can commit TXs, add the block to the chain, and empty the TX queue
        block = Block(self.tx_queue, self.last_block().hash(), sig)
        self.add_block(block)
        self.empty_tx_queue()
        return block
        
    def empty_tx_queue(self):
        self.tx_queue = {}
        
    def add_block(self, block):
        if not self.is_block_valid(block):
            print('New block is invalid')
            return
        
        self.blocks[block.hash()] = block
        
    def find_block_by(self, fun): return next((b for b in self.blocks.values() if fun(b)), None)
        
    def last_block(self):
        current_block = self.genesis_block()
        while True:
            next_block = self.find_block_by((lambda b: b.prev_block_hash == current_block.hash()))
            if next_block is None:
                break
            
            current_block = next_block
        return current_block
        
    def end_state(self): return self.end_state_for_block(self.last_block())
        
    ## Block methods
    def is_block_valid(self, block):
        if block.hash() == self.genesis_block().hash():
            return True
        
        # check that prev block is valid
        if (block.prev_block_hash not in self.blocks or 
                not self.is_block_valid(self.blocks[block.prev_block_hash])):
            print('Previous block w/ hash {0} not valid.'.format(block.prev_block_hash))
            return False
        
        # TODO: check timestamp
        # TODO: check difficulty, block number, tx root
        # TODO: check proof of work
        
        return self.end_state_signature(block) == block.end_state_signature
        
    def end_state_for_block(self, block):
        if block.hash() == self.genesis_block().hash():
            return self.genesis_world_state()
        
        state = self.end_state_for_block(self.blocks[block.prev_block_hash])
        for tx in block.transactions.values():
            state = self.apply_transaction(state, tx)
        return state
        
    def end_state_signature(self, block): return self.end_state_for_block(block).signature()
        
    ## Transaction methods
    def apply_transaction(self, state, tx):
        
        # so that apply_transaction doesnt mutate anything
        state = copy.deepcopy(state)
        
        sender_account = state.accounts[tx.sender_addr]
        if tx.nonce != sender_account.nonce:
            raise Exception('Transaction nonce must match that of the sender account')
        sender_account.nonce += 1
        
        # TODO: check well formed tx
        # TODO: do GAS calcs
        if tx.amount > sender_account.balance:
            raise Exception('{0} only has {1} balance. Not enough to cover {2} amount'.format(tx.sender_addr,
                            sender_account.balance, tx.amount))
           
        # a None receiver_addr signals that it is a Contract Creation!
        if tx.receiver_addr is None:
            if tx.data is None:
                raise Exception('Contract creation must provide code via the data argument')
        
            new_contract = Account(Hashable.hash_fn(tx.data), 0, 0, tx.data, {}, tx.hash())
            state.accounts[new_contract.address] = new_contract
            return state
    
        # if trying to send ether to accnt that doesnt exist --> create it
        if tx.receiver_addr not in state.accounts:
            state.accounts[tx.receiver_addr] = Account(tx.reciever_addr, 0, 0, None, {}, tx.hash())
            
        # move the ether
        sender_account.balance -= tx.amount
        receiver_account = state.accounts[tx.receiver_addr]
        receiver_account.balance += tx.amount
        
        # call the Contract code if the receiver account is a Contract
        if receiver_account.type() == Account.CONTRACT:
            receiver_account.call_contract(None if tx.data is None else json.loads(tx.data))
        return state
    
# Main
blockchain = BlockChain()
print('Initial world state is now:')
print(blockchain.end_state())

# REPL
# read-eval-print loop --> provides programmer w interactive programming environ
while True:
    try:
        # raw_input --> input always read in as string (renamed as input() in python 3.0)
        input_line = input('Submit a transac formatted as: from_addr to_addr nonce amount \'data\'\n')
        from_addr, to_addr, nonce, amount, data = input_line.split(' ', 4)
    
        print(data)
        #typefy inputs
        def nonify(string): return None if string == 'None' else string
        to_addr, nonce, amount, data = nonify(to_addr), int(nonce), int(amount), nonify(data.strip("'"))
        
        # enqueue transac and mine new block
        blockchain.enqueue_transaction(Transaction(from_addr, to_addr, nonce, amount, data))
        block = blockchain.mine_new_block()
        [tx] = block.transactions.values()
        end_state = blockchain.end_state()
    except KeyboardInterrupt:
        break
    except Exception as e:
        print('Invalid transaction. Try again please')
        print(e)
        blockchain.empty_tx_queue()
        continue
    
    print('###############')
    print('\nTransaction submitted')
    print('Mined new block{0}\n It contains one transaction {1}'.format(block.hash(), tx.hash()))
    print('\nThe world state is now:')
    print(end_state)
    
    
    
    
    
        
        
        
        
        