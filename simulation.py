""" All times are in milliseconds.

The script takes several parameters specified by PARAMS.

Overall layout:

There are 3 system components: jobs, front ends, and servers.  Front ends are
responsible for maintaining the (stale) state for servers, and placing jobs on
servers according to some algorithm.

The Simulation class handles running the simulation.  It adds event objects to
an event queue, and runs the simulation until all jobs have completed.  Useful
data is collected using a StatsManager object.
"""
#TODO: change all syntax:
#identation
#def () and class ()
##test to see if random.seed works for everywhere
##add a unique ID for FEs and servers (rewrite to_stirng)
##change all self.servers and self.front_ends into Simulation.schedulers and 
#Simulation.workers
##Remove user option, load_metric only returns total queue length
##Logging system.
import copy
import logging
import math
import os
import Queue
import collections
import random
import sys

import stats as stats_mod
        
# Log levels
LEVELS = {'debug': logging.DEBUG,
          'info': logging.INFO,
          'warning': logging.WARNING,
          'error': logging.ERROR,
          'critical': logging.CRITICAL}

def get_normalized_list(input_str):
    """ Returns the comma-separated input string as a normalized list. """
    items = input_str.split(",")
    total = 0.0
    for item in items:
        total += float(item)
    temp_total = 0
    for index, item in enumerate(items):
        temp_total += float(item)
        items[index] = temp_total / total
    return items

def get_int_list(input_str):
    """ Returns the comma-separated input string as a list of integers. """
    items = input_str.split(",")
    for index, item in enumerate(items):
        items[index] = int(item)
    return items

# Parameters
# param name => [convert func, default value]
PARAMS = {'num_schedulers': [int, 1],             # number of schedulers
          'num_workers': [int, 1000],       # number of workers
          # 'num_users': [int, 10],           # number of users
          'total_time': [int, 1e4],   # time over which jobs are arriving
          'scheduler_type': [str, "per_task_sampling"],

          # Ratio of number of total probes to number of tasks in each job. -1
          # signals that all machines should be probed. #TODO: make -1 working here
          'probes_ratio': [int, 2],

          # Options are "poisson" or "uniform". Describes the interval between
          # two jobs.
          'job_arrival_distribution': [str, "poisson"],
          # Arrival delay on each scheduler (the mean arrival time between two jobs)
          'job_arrival_delay': [float, 40],

          # task_distribution describes the distribution of the number of tasks
          # in a job. Choices are constant (in which case all jobs have
          # 'num_tasks' tasks) or bimodal, in which case 1/6 of the jobs have
          # 200 tasks, and the rest have 10 tasks.
          'task_distribution': [str, "constant"],
          # tasks per job (only used for constant distribution)
          'num_tasks': [int, 100],          
          
          # Across jobs, task duration subjects to [exponential/constant] 
          # distribution. In one job, all tasks have the same duration
          # Distribution of task lengths.  If set to "constant" or
          # "exponential", tasks will be distributed accordingly, with mean
          # task_length.  If set to "facebook", tasks will be distributed based
          # on what was observed from the facebook data: 95% of tasks in a job
          # will have length task_length, and 5% will have length
          # task_length + x, where x is exponentially distributed with mean
          # 0.1 * task_length.
          'task_duration_distribution': [str, "exponential"],
          'task_duration': [int, 100],        # duration of task

          'log_level': [str, "info"], #TODO: make logging working
          'network_delay': [int, 1], # Network delay
          'deterministic': [lambda x: x == "True", True], # Use fixed workload
          'random_seed': [int, 1],   # Seed to use for workload generation
          'first_time': [lambda x: x == "True", True], # Whether this is the #TODO: not sure how this works
                                                      # first in a series of
                                                      # trials (used for
                                                      # writing output files)
          'file_prefix': [str, 'results'],
          'results_dir': [str, 'raw_results'],
          # queue_selection choices are "greedy", which places a single task
          # on each of the n least loaded nodes, and "pack", which
          # packs multiple tasks on each node to minimize the overall queue
          # length.
          'queue_selection': [str, 'greedy'], # need to be more greedy here: FIFO in Scheduler
          #TODO: delete queue_selection?
          # Whether extra queue state should be recorded.
          'record_queue_state': [lambda x: x == "True", False],
          # The metric to return when a server is probed for its load.  Options
          # are 'total', which returns the total queue length, 'estimate',
          # which returns an estimated queue length based on other probes it's
          # received, and 'per_user_length', which returns the length of the
          # queue for that particular user, and 'per_user_estimate', which
          # returns an estimate of when a task for the given user will be run.
          'load_metric': [str, 'total'],
          # Comma separated list of relative demands for each user.  When #TODO: delete this?
          # creating tasks, they are assigned randomly to users based on these
          # demands.  An empty list (the default) means that all users have equal demand.
          'relative_demands': [get_normalized_list, []],
          # comma separated list of relative weights with which to run tasks
          # for each user.  Currently, only integers are supported.
          'worker_weights': [get_int_list, []]

          'load': [float, 1] #TODO: how to change the load? confirm that load is the percentage of busy worker

         }

def get_param(key):
    return PARAMS[key][1]

def output_params():
    results_dirname = get_param('results_dir')
    f = open(os.path.join(results_dirname, 
                          "%s.params" % get_param("file_prefix")), "w")
    for key, value in PARAMS.items():
        f.write("%s: %s\n" % (key, value[1]))
    f.close()

def set_param(key, val):
    convert_func = PARAMS[key][0]
    PARAMS[key][1] = convert_func(val)

###############################################################################
#                    Components: Jobs, Servers, oh my!                        #
###############################################################################

class Job(object):
    """ Represents a job.
            job = Job(last_job_arrival, num_tasks, task_duration,
                      self.stats_manager, scheduler.id_str + ":" + str(count), Simulation.workers)
    Attributes:
        arrival_time: Time the job arrives at the front end.
        num_tasks: Integer specifying the number of tasks needed for the job.
        longest_task: Runtime (in ms) of the longest task.
    """
    def __init__(self, arrival_time, num_tasks, 
                 task_duration, stats_manager, id_str, workers): #TODO: do not know some of params
        self.arrival_time = arrival_time
        self.first_task_completion = -1
        self.completion_time = -1
        self.workers = workers
        self.num_tasks = num_tasks
        self.stats_manager = stats_manager
        self.tasks_finished = 0
        self.id_str = str(id_str)
        self.longest_task = 0

        self.task_duration = task_duration
        self.task_counter = 0
        # self.task_index = 0
        
    def get_task_length(self, task_id):
        """ Returns the time the current task takes to execute.

        This should only be called once for each task! Otherwise it is likely
        to return inconsistent results.
        """
        task_length = self.task_length
        if get_param("task_length_distribution") == "exponential":
            task_length = random.expovariate(1.0 / self.task_length)
        elif get_param("task_length_distribution") == "facebook":
            if random.random() > 0.95:
                task_length += random.expovariate(10.0 / self.task_length)
        self.longest_task = max(self.longest_task, task_length)
        return task_length
        
    def task_finished(self, current_time):
        """ Should be called whenever a task completes.
        
        Sends stats to the stats manager.
        """
        if self.tasks_finished == 0:
            self.first_task_completion = current_time
        self.tasks_finished += 1
        self.stats_manager.task_finished(self.user_id, current_time)
        if self.tasks_finished == self.num_tasks:
            self.completion_time = current_time
            self.stats_manager.job_finished(self)
        
    def response_time(self):
        assert(self.completion_time != -1)
        return self.completion_time - self.arrival_time
    
    def service_time(self):
        assert(self.completion_time != -1)
        assert(self.first_task_completion != -1)
        return self.completion_time - self.first_task_completion
    
    def wait_time(self):
        assert(self.first_task_completion != -1)
        return self.first_task_completion - self.arrival_time
        
class Worker(object):
    """ Represents a back end server, which runs jobs.
    Attributes:
        queue_length: An integer specifying the total number of tasks across
            all queues (including any tasks currently running).
        last_task_completion: Time that the last task in the queue will complete
            (note that a real server wouldn't know this information; this is
            just stored for ease of simulating everything).
    """
    #TODO: remove Server.queue_length
    def __init__(self, id_str, stats_manager):
        # List of queues for each user, indexed by the user id.  Each queue
        # contains (task_length, job) pairs.
        # self.queues = []
        self.queue = collections.deque
        # Time the currently running task was started (if there is one).
        self.time_started = 0
        self.id_str = str(id_str) #TODO: do not know what this used for
        self.stats_manager = stats_manager
        # An ordered list of probes received for this machine
        self.probes = [] #TODO: remove?
        self.logger = logging.getLogger("Worker")
        
        if self.worker_weights == []: #TODO: remove?
          pass
        
    def probe_load(self, current_time): #TODO: Override this method in other schedulers
        """ Returns the current load (queue length) on the machine, based on 'load_metric'.
        """
        return len(self.queue)
        
    def __get_num_rounds(self, user_id, queue_length):
        """ Returns the number of rounds it would take to empty the queue. """
        return math.ceil(float(queue_length) / self.relative_weights[user_id])

    def queue_task(self, job, current_time):
        """ Adds the given job to the queue of tasks.
        
        Begins running the task, if there are no other tasks in the queue.
        Returns a TaskCompletion event, if there are no tasks running.
        """
        #TODO: re write Front End, use one queue.
        job.task_counter++
        task_id = job.task_counter
        self.queue.append((task_id, job))
        self.stats_manager.task_queued(job.user_id, current_time)
        if len(self.queue) > 0:
            # There aren't any tasks currently running, so launch this one.
            return [self.__launch_task(current_time)]
        
    def task_finished(self, task_id, job, current_time):
        """ Removes the task from the queue, and begins running the next task.
        
        Returns a TaskCompletion for the next task, if one exists. """
        # task_finished(self.task_id, self.job, current_time)
        assert(len(job.queue) > 0)
        self.queue.remove((task_id, job)) # not finished
        if len(job.queue) > 0:
            return [self.__launch_task(current_time)]
        
    def __launch_task(self, current_time):
        """ Launches the next task in the queue.
        
        Returns an event for the launched task's completion.
        """
        #TODO: simplify below
        assert len(self.queue) > 0
        tasks_per_round = self.relative_weights[self.current_user]
            
        self.task_count += 1
        if self.task_count >= tasks_per_round:
            # Move on to the next user.
            self.task_count = 0
            self.current_user = (self.current_user + 1) % self.num_users

        while len(self.queues[self.current_user]) == 0:
            self.current_user = (self.current_user + 1) % self.num_users
            self.task_count = 0
        # Get the first task from the queue
        task_id, job = self.queue.popleft()
        # task_length, job = self.queues[self.current_user][0]
        # assert job.user_id == self.current_user
        event = (current_time + job.task_duration, TaskCompletion(task_id, job, self))
        self.stats_manager.task_started(self.current_user, current_time)
        self.time_started = current_time

        return event


class Scheduler(object):
  pass

class PerTaskSamplingScheduler(Scheduler):
    """ Represents a front end server, which places jobs.
    """
    def __init__(self, workers, id_str, stats_manager):
        self.workers = workers
        self.stats_manager = stats_manager
        self.queue_lengths = [] # The probed queue length result
        self.id_str = str(id_str)
        self.logger = logging.getLogger("PerTaskSamplingScheduler")

        #TODO: When all workers are busy: put job in queue, wait for free workers?
        #Or, just put it in the worker queue?
        self.queue = Queue.PriorityQueue()

        #TODO: Logging: log out the result here, see why
        while len(self.queue_lengths) < len(workers):
            self.queue_lengths.append(0)
        
    def place_job(self, job, current_time):
        """ Begins the process of placing the job and returns the probe events.
        """
        #TODO: add a task_id here?
        probe_events_list = []
        for i in range(job.num_tasks):
          probe_list = random.sample(range(get_param("num_workers")), get_param("probes_ratio"))
          network_delay = get_param("network_delay")
          probe = Probe(self, job, probe_list)
          probe_events_list.attach((current_time+network_delay, probe_event)) #TODO: make this event correct

        #TODO: test to see if this shuffle returns the same result every time
        # random.shuffle(servers_copy)

        assert(len(probe_list) <= len(self.workers)), "More probes than workers"
        return probe_events_list
    
    def probe_completed(self, job, queue_lengths, current_time):
        """ Sends the task to worker(s) based on the result of the probe.

        probe_completed(self.job, self.queue_lengths,
                                                  current_time)
        """
        events = [] #TODO: this events is used to be compatiable with batch scheduler
        task_arrival_time = current_time + get_param("network_delay") # Arrive worker.
        queue_lengths.sort(key = lambda k: k[1])
        worker_candidate_index = queue_lengths[0][0]
        events.append((task_arrival_time, TaskArrival(worker_index, job)))
        return events

    #TODO: factor out this get_best_worker method
    # def get_best_n_queues(self, queue_lengths, n):


class IdealScheduler (FrontEnd):
    def __init__ (self):
        super(IdealScheduler,self)
        # When all workers are busy, put them in the Scheduler's queue
        self.task_queue = Queue.PriorityQueue()


class RandomSamplingScueduler (FrontEnd):
    pass


class PerTaskSamplingScheduler (FrontEnd):
    pass


class BatchSamplingScheduler (FrontEnd):
    pass


class LateBindingScheduler (FrontEnd):
    pass


###############################################################################
#                                   Events                                    #
###############################################################################

class Event(object):
    """ Abstract class representing events. """
    def __init__(self):
        raise NotImplementedError("Event is an abstract class and cannot be "
                                  "instantiated directly")
    
    def run(self, current_time):
        """ Returns any events that should be added to the queue. """
        raise NotImplementedError("The run() method must be implemented by "
                                  "each class subclassing Event")
        
class RecordQueueState(Event):
    """ Event to periodically record information about the worker queues. """
    def __init__(self, servers, stats_manager, query_interval):
        self.servers = servers
        self.stats_manager = stats_manager
        self.query_interval = query_interval
        
    def run(self, current_time):
        queue_lengths = []
        for server in self.servers:
            queue_lengths.append(server.queue_length)
        self.stats_manager.record_queue_lengths(queue_lengths)
        
        return [(current_time + self.query_interval, self)]
        
class JobArrival(Event):
    """ Event to handle jobs arriving at a front end. """
    def __init__(self, job, scheduler):
        self.job = job
        self.scheduler = scheduler
        
    def run(self, current_time):
        return self.scheduler.place_job(self.job, current_time)
    
class TaskArrival(Event):
    """ Event to handle a task arriving at a server. """
    def __init__(self, worker_index, job):
        self.worker_index = worker_index
        self.job = job
        
    def run(self, current_time):
        return Simulation.workers[self.worker_index].queue_task(self.job, 
          current_time)
        
class TaskCompletion(Event):
    """ Event to handle tasks completing. """
    def __init__(self, task_id, job, worker):
        self.task_id = task_id
        self.job = job
        self.worker = worker

    def run(self, current_time):
        self.job.task_finished(current_time) #TODO: need task_id here?
        return self.worker.task_finished(self.task_id, self.job, current_time)
        
class Probe(Event):
    """ Event to probe a list of servers for their current queue length.
    Probe(self, job, probe_list)
    This event is used for both a probe and a probe reply to avoid copying
    state to a new event.  Whether the queue_lengths variable has been
    populated determines what type of event it's currently being used for. """

    def __init__(self, scheduler, job, workers):
        self.scheduler = scheduler
        self.job = job
        self.workers = workers
        self.queue_lengths = []
    
    def run(self, current_time):
        if len(self.queue_lengths) == 0: # If this probe is not finished
            # Need to collect state.
            for worker_index in self.workers:
                self.queue_lengths.append((worker_index,
                                           Simulation.workers[worker_index].probe_load(current_time)))
            return [(current_time + get_param("network_delay"), self)]
        else: # If this probe is finished, and passed back to scheduler
            return self.scheduler.probe_completed(self.job, self.queue_lengths,
                                                  current_time)

###############################################################################
#               Practical things needed for the simulation                    #
###############################################################################

class StatsManager(object):
    """ Keeps track of statistics about job latency, throughput, etc.
    """
    def __init__(self):
        self.total_enqueued_tasks = 0
        # Total enqueued jobs per-user over time, stored as a list of
        # (time, queue_length) tuples.
        self.enqueued_tasks = []
        for user in range(get_param("num_users")):
            self.enqueued_tasks.append([])
        self.completed_jobs = []
        
        # Number of running tasks for each user (indexed by user id).
        # Stored as a list of (time, queue_length) tuples for each user.
        self.running_tasks = []
        # List of (time, queue_length) tuples describing the total number of
        # running tasks in the cluster.
        self.total_running_tasks = []
        for user in range(get_param("num_users")):
            self.running_tasks.append([])

        self.logger = logging.getLogger("StatsManager")        
        
        # Logging for queue lengths.
        # Length of individual queues, at fixed intervals.
        self.queue_lengths = []
        # Number of empty queues, at fixed intervals.
        self.empty_queues = []

        # Calculate utilization
        avg_num_tasks = get_param("num_tasks")
        if get_param("task_distribution") == "bimodal":
            avg_num_tasks = (200. / 6) + (10 * 5. / 6)
        tasks_per_milli = (float(get_param('num_schedulers') * avg_num_tasks) /
                           get_param('job_arrival_delay'))

        capacity_tasks_per_milli = (float(get_param('num_workers')) /
                                    get_param('task_length'))
        self.utilization = tasks_per_milli / capacity_tasks_per_milli

        self.logger.info("Utilization: %s" % self.utilization)
        
    def record_queue_lengths(self, queue_lengths):
        num_empty_queues = 0
        for length in queue_lengths:
            if length == 0:
                num_empty_queues += 1
            self.queue_lengths.append(length)
        self.empty_queues.append(num_empty_queues)

    def task_queued(self, user_id, current_time):
        num_queued_tasks = 1
        queued_tasks_history = self.enqueued_tasks[user_id]
        if len(queued_tasks_history) > 0:
            num_queued_tasks = queued_tasks_history[-1][1] + 1
            assert num_queued_tasks >= 1
        queued_tasks_history.append((current_time, num_queued_tasks))
        self.total_enqueued_tasks += 1
        
    def task_started(self, user_id, current_time):
        """ Should be called when a task begins running. """
        # Infer number of currently running tasks.
        num_running_tasks = 1
        if len(self.running_tasks[user_id]) > 0:
            num_running_tasks = self.running_tasks[user_id][-1][1] + 1
            assert num_running_tasks >= 1
        self.running_tasks[user_id].append((current_time, num_running_tasks))
        
        total_running_tasks = 1
        if len(self.total_running_tasks) > 0:
            total_running_tasks = self.total_running_tasks[-1][1] + 1
            assert total_running_tasks > 0
        self.total_running_tasks.append((current_time, total_running_tasks))

    def task_finished(self, user_id, current_time):
        assert len(self.running_tasks[user_id]) > 0
        num_running_tasks = self.running_tasks[user_id][-1][1] - 1
        assert num_running_tasks >= 0
        self.running_tasks[user_id].append((current_time, num_running_tasks))
        
        assert len(self.total_running_tasks) > 0
        total_running_tasks = self.total_running_tasks[-1][1] - 1
        assert total_running_tasks >= 0
        self.total_running_tasks.append((current_time, total_running_tasks))
        
        assert self.total_enqueued_tasks > 0
        self.total_enqueued_tasks -= 1
        queued_tasks_history = self.enqueued_tasks[user_id]
        assert len(queued_tasks_history) > 0
        num_queued_tasks = queued_tasks_history[-1][1] - 1
        assert num_queued_tasks >= 0
        queued_tasks_history.append((current_time, num_queued_tasks))
        
    def job_finished(self, job):
        self.completed_jobs.append(job)

    def output_stats(self):
        assert(self.total_enqueued_tasks == 0)
        results_dirname = get_param('results_dir')
        try:
            os.mkdir(results_dirname)
        except:
            pass
        
        self.output_running_tasks()
        self.output_bucketed_running_tasks()
        #self.output_queue_size()
       # self.output_queue_size_cdf()
        #self.output_job_overhead()
        self.output_response_times()
        
        for user_id in range(get_param("num_users")):
            self.output_response_times(user_id)
         
        # This can be problematic for small total runtimes, since the number
        # of jobs with 200 tasks may be just 1 or 0.    
        if get_param("task_distribution") == "bimodal":
            self.output_per_job_size_response_time()
            
    def output_bucketed_running_tasks(self):
        bucketed_running_tasks_per_user = []
        bucket_interval = 100
        
        results_dirname = get_param("results_dir")
        filename = os.path.join(results_dirname,
                                "%s_bucketed_running_tasks" %
                                get_param("file_prefix"))
        file = open(filename, "w")
        file.write("time\t")

        for user_id in range(get_param("num_users")):
            bucketed_running_tasks = []
            # Total number of CPU millseconds used during this bucket.
            cpu_millis = 0
            current_running_tasks = 0
            # Last time we got a measurement for the number of running tasks.
            previous_time = 0
            # Beginning of the current bucket.
            bucket_start_time = 0
            for time, running_tasks in self.running_tasks[user_id]:
                while time > bucket_start_time + bucket_interval:
                    # Roll over to next bucket.
                    bucket_end_time = bucket_start_time + bucket_interval
                    cpu_millis += (current_running_tasks *
                                   (bucket_end_time - previous_time))
                    bucketed_running_tasks.append(cpu_millis)
                    cpu_millis = 0
                    previous_time = bucket_end_time
                    bucket_start_time = bucket_end_time
                cpu_millis += current_running_tasks * (time - previous_time)
                previous_time = time
                current_running_tasks = running_tasks
            bucketed_running_tasks_per_user.append(bucketed_running_tasks)
            
        file.write("total\n")
            
        # Write bucketed running tasks to file.
        num_buckets = len(bucketed_running_tasks_per_user[0])
        for bucket_index in range(num_buckets):
            file.write("%d\t" % (bucket_index * bucket_interval))
            total_cpu_millis = 0
            for user_id in range(get_param("num_users")):
                running_tasks = bucketed_running_tasks_per_user[user_id]
                if len(running_tasks) > bucket_index:
                    cpu_millis = running_tasks[bucket_index]
                else:
                    cpu_millis = 0
                total_cpu_millis += cpu_millis
                file.write("%d\t" % cpu_millis)
            file.write("%d\n" % total_cpu_millis)
            
    def output_running_tasks(self):
        """ Output the number of tasks running over time.
        
        Outputs the number of tasks per user, as well as the number of running
        tasks overall.
        """
        results_dirname = get_param("results_dir")
        for user_id in range(get_param("num_users")):
            filename = os.path.join(results_dirname, "%s_running_tasks_%d" %
                                    (get_param("file_prefix"), user_id))
            running_tasks_file = open(filename, "w")
            self.write_running_tasks(running_tasks_file,
                                     self.running_tasks[user_id])
            running_tasks_file.close()
            
        # Output aggregate running tasks.
        filename = os.path.join(results_dirname, "%s_running_tasks" %
                                get_param("file_prefix"))
        running_tasks_file = open(filename, "w")
        self.write_running_tasks(running_tasks_file, self.total_running_tasks)
        running_tasks_file.close()    
        
    def write_running_tasks(self, file, tasks_list):
        """ Writes a list of (time, num_tasks) tuples to file.
        
        Consolidates tuples occurring at the same time, and writes the
        list in reverse order. """
        file.write("time\trunning_tasks\n")
        previous_time = -1
        # Write in reverse order so that we automatically get the last event
        # for each time.
        for time, running_tasks in reversed(tasks_list):
            if time != previous_time:
                if previous_time != -1:
                    file.write("%d\t%d\n" % (previous_time, running_tasks))
                file.write("%d\t%d\n" % (time, running_tasks))
            previous_time = time
  
    def output_queue_size(self):
        """ Output the queue size over time. """
        results_dirname = get_param('results_dir')
        filename = os.path.join(results_dirname,
                                '%s_%s' % (get_param('file_prefix'),
                                           'queued_tasks'))
        queued_tasks_file = open(filename, 'w')
        queued_tasks_file.write('time\ttotal_queued_tasks\n')
        for time, queued_tasks in self.enqueued_tasks:
            queued_tasks_file.write('%s\t%s\n' % (time, queued_tasks))
        queued_tasks_file.close()
        
    def output_queue_size_cdf(self):
        """ Output the cumulative probabilities of queue sizes. 
        """
        results_dirname = get_param("results_dir")
        filename = os.path.join(results_dirname,
                                "%s_%s" % (get_param("file_prefix"),
                                           "queue_cdf"))
        queue_cdf_file = open(filename, "w")
        queue_cdf_file.write("%ile\tQueueSize\n")
        
        queue_sizes = []
        for time, queued_tasks in self.enqueued_tasks:
            queue_sizes.append(queued_tasks)
        queue_sizes.sort()
        
        stride = max(1, len(queue_sizes) / 200)
        for index, queue_size in enumerate(queue_sizes[::stride]):
            percentile = (index + 1) * stride * 1.0 / len(queue_sizes)
            queue_cdf_file.write("%f\t%f\n" % (percentile, queue_size))
        queue_cdf_file.close()
            
    def output_job_overhead(self):
        """ Write job completion time and longest task for every job to a file.
        """
        results_dirname = get_param("results_dir")
        filename = os.path.join(results_dirname,
                                "%s_%s" % (get_param("file_prefix"),
                                           "overhead"))
        overhead_file = open(filename, "w")
        overhead_file.write("ResponseTime\tLongestTask\n")
        for job in self.completed_jobs:
            overhead_file.write("%d\t%d\n" %
                                (job.response_time(), job.longest_task))
        overhead_file.close()

    def output_response_times(self, user_id=-1):
        """ Aggregate response times, and write job info to file.
        
        Parameters:
            user_id: An optional integer specifying the id of the user for
                whom to output aggregate response time info.  If absent,
                outputs delay summaries for all users. """
        results_dirname = get_param('results_dir')
        user_id_suffix = ""
        if user_id != -1:
            user_id_suffix = "_%d" % user_id
        filename = os.path.join(results_dirname,
                                '%s_%s%s' %
                                (get_param('file_prefix'), 'response_vs_time',
                                 user_id_suffix))
        response_vs_time_file = open(filename, 'w')
        response_vs_time_file.write('arrival\tresponse time\n')
        response_times = []
        # Job overhead is defined to the the total time the job took to run,
        # divided by the runtime of the longest task. In other words, this is
        # the overhead of running on a shared cluster, compared to if the job
        # ran by itself on a cluster.
        job_overhead = 0.0
        for job in self.completed_jobs:
            # Doing it this way, rather than just recording the response times
            # for all users in one go, is somewhat inefficient.
            if user_id != -1 and job.user_id != user_id:
                continue
            assert(job.wait_time >= -0.00001)
            response_vs_time_file.write('%s\t%s\n' % (job.arrival_time,
                                                      job.response_time()))
          
            response_times.append(job.response_time())
            # Not really fair to count network overhead in the job overhead.
            normalized_response_time = (job.response_time() -
                                        3 * get_param("network_delay"))
            job_overhead += normalized_response_time * 1.0 / job.longest_task
        job_overhead = (job_overhead / len(self.completed_jobs)) - 1
        
        # Append avg + stdev to each results file.
        n = get_param("num_tasks")
        probes_ratio = get_param("probes_ratio")
        filename = os.path.join(
            results_dirname, "%s_response_time%s" % (get_param('file_prefix'),
                                                     user_id_suffix))
        if get_param('first_time'):
            f = open(filename, 'w')
            f.write("n\tProbesRatio\tUtil.\tMeanRespTime\tStdDevRespTime\t"
                    "5Pctl\t50Pctl\t95Pctl\t99PctlRespTime\t"
                    "NetworkDelay\tJobOverhead\tNumServers\tAvg#EmptyQueues\n")
            f.close()
        f = open(filename, 'a')
        # Currently, only the response time is written to file.
        avg_empty_queues = -1
        if len(self.empty_queues) > 0:
            avg_empty_queues = stats_mod.lmean(self.empty_queues)
        response_times.sort()
        f.write(("%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s"
                 "\t%s\t%s\n") %
                (n, probes_ratio, self.utilization,
                 stats_mod.lmean(response_times), 
                 stats_mod.lstdev(response_times),
                 self.percentile(response_times, 0.05),
                 self.percentile(response_times, 0.5),
                 self.percentile(response_times, 0.95),
                 self.percentile(response_times,.99),
                 get_param("network_delay"), job_overhead,
                 get_param("num_workers"), avg_empty_queues))
        f.close()
        
        # Write CDF of response times
        #filename = os.path.join(results_dirname, "%s_response_time_cdf" %
        #                       get_param("file_prefix"))
        #f = open(filename, "w")
        #stride = max(1, len(response_times) / 200)
        #for index, response_time in enumerate(response_times[::stride]):
        #    percentile = (index + 1) * stride * 1.0 / len(response_times)
        #    f.write("%f\t%f\n" % (percentile, response_time))
        #f.close()
            
    def output_per_job_size_response_time(self):
        """ Output extra, separate files, with response times for each job size.
        """
        results_dirname = get_param('results_dir')
        num_tasks_to_response_times = {}
        for job in self.completed_jobs:
            if job.num_tasks not in num_tasks_to_response_times:
                num_tasks_to_response_times[job.num_tasks] = []
            num_tasks_to_response_times[job.num_tasks].append(
                job.response_time())
            
        n = get_param("num_tasks")
        probes_ratio = get_param("probes_ratio")
        for num_tasks, response_times in num_tasks_to_response_times.items():
            filename = os.path.join(
                results_dirname,
                "%s_response_time_%s" % (get_param("file_prefix"),
                                         num_tasks))
            if get_param('first_time'):
                f = open(filename, 'w')
                f.write("n\tProbesRatio\tUtil.\tMean\tStdDev\t99Pctl\t"
                        "NetworkDelay\n")
                f.close()
            f = open(filename, 'a')
            f.write("%s\t%s\t%s\t%s\t%s\t%s\t%s\n" %
                    (n, probes_ratio, self.utilization,
                     stats_mod.lmean(response_times), 
                     stats_mod.lstdev(response_times),
                     stats_mod.lscoreatpercentile(response_times,.99),
                     get_param("network_delay")))
            f.close()
        

    def write_float_array(self, file_suffix, arr, sorted=False):
      filename = os.path.join(
          get_param('results_dir'),
          '%s_%s' % (get_param('file_prefix'), file_suffix))
      f = open(filename, "w")
      if sorted:
          arr.sort()
      for i in range(len(arr)):
          f.write("%d %f\n" % (i, arr[i]))
      f.close()
      
    def percentile(self, values, percent):
        """Finds the percentile of a list of values.
        
        Copied from: http://code.activestate.com/recipes/511478-finding-the-percentile-of-the-values/.
        
        Arguments:
            N: List of values. Note N MUST BE already sorted.
            percent: Float value from 0.0 to 1.0.
        
        Returns:
            Float specifying percentile of the values.
        """
        if not values:
            return None
        k = (len(values)-1) * percent
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return values[int(k)]
        d0 = values[int(f)] * (c-k)
        d1 = values[int(c)] * (k-f)
        return d0+d1

class Simulation(object):
    """
    Attributes:
        event_queue: A priority queue of events.  Events are added to queue as
            (time, event) tuples.
    """
    schedulers = []
    workers = []
    scheduler_types = {'per_task_sampling': PerTaskSamplingScheduler} #TODO:
    def __init__(self, num_schedulers, num_workers):
      #TODO: pass number of front ends and serves acquired from CLI
        self.current_time_ms = 0
        self.event_queue = Queue.PriorityQueue()
        self.total_jobs = 0
        self.logger = logging.getLogger("Simulation")
        self.stats_manager = StatsManager()
        self.worker_weights = get_param("worker_weights")

        # Initialize workers
        self.num_workers = num_workers
        self.scheduler_type = get_param('scheduler_type') #TODO: move this to create_jobs?
        assert self.scheduler_type in ['omniscient_scheduler',
         'ramdom_sampling', 'per_task_sampling', 'batch_sampling', 'late_binding']
        self.scheduler = self.scheduler_types[self.scheduler_type]

        while len(Simulation.workers) < self.num_workers:
            Simulation.workers.append(Worker(len(Simulation.workers), self.stats_manager,
                                       self.num_users)) 
        #TODO: pass server parameters at here? --> RTT, processing time, etc

        # Initialize schedulers
        self.num_schedulers = num_schedulers
        
        while len(Simulation.schedulers) < self.num_schedulers:
            Simulation.schedulers.append(self.scheduler(
                Simulation.workers, len(self.schedulers), self.stats_manager))

    def create_jobs(self, total_time):
        """ Creates num_jobs jobs on EACH front end.

        Actually, create a lot of jobs according to the distributions, and put them in a queue
        This is the global view queue: used for event driven simulation
        
        #TODO: cannot change load now
        # so, every front end (scheduler) gets a lot of jobs, and send them to workers

        Parameters:
            total_time: The maximum time of any possible job created. We
                try to create jobs filling most of the allocated time.
        """                                                                       
        task_distribution = get_param('task_distribution')
        num_tasks = get_param('num_tasks')
        task_duration_distribution = get_param('task_duration_distribution')
        avg_task_duration = get_param('task_duration')
        avg_arrival_delay = get_param('job_arrival_delay')
        job_arrival_distribution = get_param('job_arrival_distribution')

        for scheduler in Simulation.schedulers:
            last_job_arrival = 0
            count = 0

            while True:
                if job_arrival_distribution == "constant":
                    new_last = last_job_arrival + avg_arrival_delay
                elif job_arrival_distribution == "poisson":
                    # If the job arrivals are a Poisson process, the time
                    # between jobs follows an exponential distribution.  
                    new_last = last_job_arrival + \
                        random.expovariate(1.0/avg_arrival_delay)
                else: 

                # See if we've passed the end of the experiment
                if new_last > total_time:
                    break
                else: 
                    last_job_arrival = new_last
                
                if task_distribution == "bimodal":
                    if random.random() > (1.0 / 6):
                        # 5/6 of the jobs have 10 tasks.
                        num_tasks = 10
                    else:
                        num_tasks = 200

                if task_duration_distribution  == "exponential":
                  task_duration = random.expovariate(1.0/avg_task_duration)
                else: raise NotImplementedError("Other task distributions not implemented.")
                #TODO: finish diff task distribution

                job = Job(last_job_arrival, num_tasks, task_duration,
                          self.stats_manager, scheduler.id_str + ":" + str(count), Simulation.workers)
                job_arrival_event = JobArrival(job, scheduler)
                self.event_queue.put((last_job_arrival, job_arrival_event))
                #TODO: print out the jobs of same priority in queue
                # see if they are randomized
                self.total_jobs += 1
                count = count + 1
    def run(self):
        """ Runs the simulation until all jobs have completed. """
        counter = 0 #TODO: not sure
        counter_increment = 1000 # Reporting frequency

        last_time = 0
        
        if get_param("record_queue_state"):
            # Add event to query queue state.
            query_interval = 1
            report_queue_state = RecordQueueState(self.servers,
                                                  self.stats_manager,
                                                  query_interval)
            self.event_queue.put((query_interval, report_queue_state))

        while len(self.stats_manager.completed_jobs) < self.total_jobs: 
        #TODO: make sure stats_manager.completed_jobs increases
            assert(not self.event_queue.empty()), "Event queue is empty before all jobs finish."
            current_time, event = self.event_queue.get() # Queue.get() will push

            assert(current_time >= last_time), "Event happending time is wrong."
            last_time = current_time

            if current_time > counter:
                counter = counter + counter_increment
            new_events = event.run(current_time) #TODO: always return a list here
            if new_events:
                for new_event in new_events:
                    self.event_queue.put(new_event) #TODO: a list of tuples
    
        self.stats_manager.output_stats()
        
        output_params()

def main(argv):
    if len(argv) > 0 and "help" in argv[0]:
      print "Usage: python simulation.py " + "".join(
          ["[%s=v (%s)] " % (k[0], k[1][1]) for k in PARAMS.items()])
      sys.exit(0)

    # Fill in any specified parameters
    for arg in argv:
        kv = arg.split("=")
        if len(kv) == 2 and kv[0] in PARAMS:
            set_param(kv[0], kv[1])
        elif kv[0] not in PARAMS:
            logging.warn("Ignoring key %s" % kv[0])

    # Sanity check
    if get_param("probes_ratio") < 1.0 and get_param("probes_ratio") != -1:
        print ("Given value, %f, is not a valid probes_ratio" %
               get_param("probes_ratio"))
        sys.exit(0)
    relative_demands = get_param("relative_demands")
    if (relative_demands != [] and \
        len(relative_demands) != get_param("num_users")):
        print ("The length of relative demands does not match the "
               "given number of users")
        sys.exit(0)
    
    relative_weights = get_param("relative_weights")
    if (relative_weights != [] and \
        len(relative_weights) != get_param("num_users")):
        print ("The length of relative weights does not match the "
               "given number of users")
        sys.exit(0)

    logging.basicConfig(level=LEVELS.get(get_param('log_level')))

    if get_param("deterministic") is True:
        random.seed(get_param("random_seed"))

    sim = Simulation(get_param("num_schedulers"), get_param("num_workers"))
    sim.create_jobs(get_param("total_time"))
    sim.run()
    
if __name__ == '__main__':
    main(sys.argv[1:])
