#!/usr/bin/python

## Import Classes
import os
import sys
import json
import uuid
import time
import redis
import base64
import socket
import platform
import multiprocessing
from threading import Thread


## Globals
version = "0.1"


## Facilitates communitcation on the bus.
class Communicator:
	bustype		= "redis"
	server		= "localhost"
	password	= None
	port		= 6379
	channel		= 0
	ttl			= 1
	verbose		= False

	
	def __init__(self):
		if self.bustype == "redis":
			self.bus = redis.StrictRedis(host = self.server, port = self.port, db = self.channel, password = self.password)


	def push(self,queue,data,reverse=False,ttl=False):
		if self.bustype == "redis":
			if reverse:
				retval = self.bus.rpush(queue,data)
			else:
				retval = self.bus.lpush(queue,data)
			if ttl: self.bus.expire(queue,ttl)
			return(retval)

	def pop(self,queue,reverse=False):
		if self.bustype == "redis":
			if reverse:
				return(self.bus.rpop(queue))
			else:
				return(self.bus.lpop(queue))

	def transfer(self,output,input):
		if self.bustype == "redis":
			return(self.bus.rpoplpush(output,input))


	def dump(self,queue,pop=False):
		if self.bustype == "redis":
			items = []
			for i in range(0,self.bus.llen(queue)):
				if pop:
					items.append(self.bus.rpop(queue))
				else:
					items.append(self.bus.lindex(queue,i))
			return(items)

	def destroy(self,key):
		if self.bustype == "redis":
			try:
				return(self.bus.delete(key))
			except:
				return(False)

	def set(self,key,value,ttl=False):
		if self.bustype == "redis":
			val = self.bus.set(key,value)
			if ttl: self.bus.expire(key,ttl)
			return(val)

	def get(self,key,ttl=False):
		if self.bustype == "redis":
			if ttl: self.bus.expire(key,ttl)
			return(self.bus.get(key))

	def show(self,pattern):
		if self.bustype == "redis":
			return(self.bus.keys(pattern))


## Gives information
class Informant:

	## Info Model
	comm = Communicator()
	instanceid = str(uuid.uuid4())
	instancehost = socket.gethostname()
	instancename = os.path.basename(sys.argv[0])
	instancestart = time.time()
	instanceclass = None
	message = None
	lastmessage = None


	## Sets status
	def status(self,message):
		self.comm.set("status_%s"%(self.instanceid),message,60)
		return(True)


	## Sets status message
	def message(self,message):
		if not self.lastmessage == self.message: self.lastmessage = self.message
		self.message = message
		return(True)


	## Updates status
	def updateStatus(self):
		message = {
					"message":self.message,
					"lastmessage":self.lastmessage,
					"class":self.instanceclass,
					"id":self.instanceid,
					"host":self.instancehost,
					"name":self.instancename,
					"starttime":self.instancestart,
					"timestamp":time.time()
		}
		return(self.status(json.dumps(message,indent=2)))


## Sends marbles to higher runs
class Elevator:
	
	## Instances
	comm = Communicator()
	info = Informant()
	info.instanceclass = "elevator"

	## Options
	upstream = None
	bustype = comm.bustype
	server = comm.server
	password = comm.password
	port = comm.port
	channel = comm.channel
	verbose = False
	pendqueue = "elevate_"



	## Init
	def __init__(self):
		self.upstream = Communicator()
		self.upstream.bustype = self.bustype
		self.upstream.server = self.server
		self.upstream.password = self.password
		self.upstream.port = self.port
		self.upstream.channel = self.channel
		self.upstream.__init__()


	## Picks up
	def lift(self,queue,data):
		elevqueue = "%s%s"%(self.pendqueue,queue)
		return(self.comm.push(elevqueue,data))


	## Lists pending marbles
	def pending(self):
		if self.verbose: print("\t[I] Checking for pending marbles...")
		query = "%s*"%(self.pendqueue)
		return(self.comm.show(query))


	## Elevates	pending marbles
	def send(self):
		self.__init__()
		pending = self.pending()
		if not pending == None:
			for queue in pending:
				dataset = self.comm.dump(queue,True)
				try:
					if self.verbose: print("\t[I] Sending data to upstream server...")
					for data in dataset:
						self.upstream.push(queue.replace(self.pendqueue,''),data)
				except:
					if self.verbose: print("\t[E] Cannot communicate with upstream server!  Returning values to original queue")
					for data in dataset:
						self.comm.push(queue,data)


	## Elevator Daemon
	def daemon(self):
		while True:
			self.send()
			time.sleep(1)




## Provides assured execution and failure handling
class Monitor:

	## State
	comm = Communicator()
	info = Informant()
	info.instanceclass = "monitor"
	id = "0"
	queue = "monitor"
	private = "_private"
	lock = "_lock"
	ttl = comm.ttl
	verbose = False


	## Init
	def __init__(self):
		self.id			= str(uuid.uuid4())
		self.private	= "%s_private"%(self.id)
		self.lock		= "%s_lock"%(self.id)


	## Inform the monitor of what queue to watch and transfer the data
	def checkout(self,public=None,private=None,lock=None):
		if public	== None: public		= self.public
		if private	== None: private	= self.private
		if lock		== None: lock		= self.lock
		try:
			data = self.comm.transfer(public,private)
			if data == None:
				if self.verbose: print("\t[M] No work in queue '%s'"%(public))
				return(False)
			else:
				if self.verbose: print("\t[M] Found '%s' in queue '%s'"%(data,public))
				message	=	{
								"id":self.id,"node":socket.gethostname(),
								"public":public,
								"private":private,
								"lock":lock,
								"timestamp":int(time.time())
							}
				self.comm.push(self.queue,json.dumps(message))
				return(data)
		except:
			return(False)


	## Close out the session
	def finish(self,private=None,lock=None):
		if private	== None: private	= self.private
		if lock		== None: lock		= self.lock
		for i in [lock,private]:
			self.comm.destroy(i)


	## Heartbeat
	def heartbeat(self,lock=None):
		if self.verbose: print("\t[M] Sending heartbeat")
		if lock == None: lock = self.lock
		try:
			self.comm.set(lock,True,self.ttl)
			if self.verbose: print("\t\t[M] Heartbeat success")
			return(True)
		except:
			if self.verbose: print("\t\t[M] Heartbeat failed")
			return(False)


	## Process monitored queue
	def monitorQueue(self):
		self.info.updateStatus()
		message = self.comm.pop(self.queue,True)
		if not message == None:
			if self.verbose: print("\t[M] Message from worker received")
			message = json.loads(message)
			if self.verbose: print("\t\t[M] Message details:")
			if self.verbose: print(json.dumps(message,indent=2)+"\n\n\n")
			c = 0
			self.comm.set(message["lock"],True,self.ttl)
			#self.comm.set(message["lock"],True,1)
			while self.comm.get(message["lock"]):
				self.info.message = "Monitoring %s"%(message["lock"])
				self.info.updateStatus()
				if self.verbose: print("\t[M] Locked for %ss"%(str(c)))
				c += 1
				time.sleep(1)
			if self.comm.dump(message["private"]):
				if self.verbose: print("\t[M] Looks like it died, adding it back to the original queue...")
				self.comm.push(message["public"],self.comm.pop(message["private"]))
			else:
				if self.verbose: print("\t[M] Job completed on its own volition")
		else:
			self.info.message = "Waiting"
			self.info.updateStatus()
			if self.verbose: print("\t[M] No messages from workers found")


	## Monitor Daemon
	def daemon(self):
		self.info.message = "Started"
		self.info.updateStatus()
		while True:
			self.monitorQueue()
			time.sleep(0.1)






## The in-script handler
class Marble:

	## Instances
	mon = Monitor()
	elev = Elevator()
	info = Informant()
	comm = Communicator()
	info.instanceclass = "marble"


	## Options
	monitored = True
	fail_after = 60
	wait_poll = 0.1
	verbose	= False


	## Heartbeat
	hbpid = None
	hbstate = False


	## Init
	def __init__(self):
		self.instancename = os.path.basename(__file__)
		self.instanceid = str(uuid.uuid4())
		self.instancehost = socket.gethostname()
		self.instancestart = time.time()


	## Sets up connection
	def connect(self,bustype=None,server=None,port=None,password=None,channel=None):
		try:
			if bustype == None: bustype = self.comm.bustype
			if server == None: server = self.comm.server
			if port == None: port = self.comm.port
			if password == None: password = self.comm.password
			if channel == None: channel = self.comm.channel
			self.comm.bustype = bustype
			self.comm.server = server
			self.comm.port = port
			self.comm.password = password
			self.comm.channel = channel
			self.comm.__init__()
			return(True)
		except:
			return(False)


	## Checks for data
	def check(self,queue):
		if self.monitored:
			data = self.mon.checkout(queue)
		else:
			data = self.comm.pop(queue)
		return(data)


	## Waits for data
	def wait(self,queue):
		hbstate = False
		data = self.check(queue)
		self.info.updateStatus()
		while data == None or data == False:
			self.info.message = "Waiting"
			self.info.updateStatus()
			time.sleep(self.wait_poll)
			if self.verbose: print("\t[I] Nothing in queue %s, waiting %s seconds..."%(queue,self.wait_poll))
			data = self.check(queue)
			self.info.updateStatus()
		if self.monitored:
			hbstate = True
			self.hbpid = Thread(target=self.heartbeat)
			self.hbpid.start()
		return(data)


	## Keeps job alive in the monitor
	def heartbeat(self):
		while self.hbstate:
			self.mon.heartbeat()
			time.sleep(self.comm.ttl / 4)


	## Tells the monitor the job is finished
	def finish(self):
		self.hbstate = False
		self.mon.finish()


	## Sends data to a queue
	def send(self,queue,data):
		self.comm.push(queue,data)
		if self.verbose: print("\t[I] Sending data to queue %s"%(queue))


	## Sends data to a queue
	def expedite(self,queue,data):
		self.comm.push(queue,data,True)
		if self.verbose: print("\t[I] Sending data to front of queue %s"%(queue))


	## Elevate a marble
	def elevate(self,queue,data):
		self.elev.lift(queue,data)
		if self.verbose: print("\t[I] Sending data to an upstream queue %s"%(queue))


	## Reports message
	def report(self,message):
		self.info.message = message
		self.info.updateStatus()




## CLI Tools
class CLI:
	comm = Communicator()


	## Display as table
	def table(data):
		row_format ="{:>15}" * (len(teams_list) + 1)
			print row_format.format("", *teams_list)
			for team, row in zip(teams_list, data):
				print row_format.format(team, *row)


	## Gets status
	def status(self):
		nodes = self.comm.show('status_*')
		display = ""
		for node in nodes:
			data = json.loads(self.comm.get(node))
			sync = time.time() - data['timestamp']
			node = data['host']
			uptime = data['timestamp'] - data['starttime']
			mrclass = data['class']
			line = '%s: %s %s %s\n'%(node,sync,mrclass,uptime)
			display += line
		print display







