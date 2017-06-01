

import subprocess
import threading
import os

import numpy as np
import zmq
import json
from uuid import uuid4

from qcodes.data.data_array import DataArray


class ControlListener(threading.Thread):
    """
    ListenToClientTask
    """
    def __init__(self, client_ready_event=None, port=8770):
        self.client_ready_event = client_ready_event
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)

        self.port = self.socket.bind_to_random_port('tcp://*',
                                                    min_port=port,
                                                    max_port=port+100,
                                                    max_tries=100)

        self.socket.setsockopt(zmq.SUBSCRIBE, b'')

        self.poller = zmq.Poller()
        self.poller.register(self.socket, zmq.POLLIN)

        threading.Thread.__init__(self)

        self.running = True

    def run(self):

        while self.running:
            socks = dict(self.poller.poll(1000))
            if socks.get(self.socket) == zmq.POLLIN:
                try:
                    msg = self.socket.recv_json()
                    ready = msg.get('client_ready', None)
                    if ready is True:
                        self.client_ready_event.set()
                    else:
                        print(msg)
                except Exception:
                    print('ups ups ups')

        self.socket.close()
        self.context.term()


class Plot():

    context = zmq.Context()
    socket = context.socket(zmq.PUB)

    port = 8876
    port = socket.bind_to_random_port('tcp://*',
                                      min_port=port,
                                      max_port=port+20,
                                      max_tries=100)
    encoding = 'utf-8'

    def __init__(self, name=None):
        name = name or uuid4().hex
        topic = 'qcodes.plot.'+name
        self.topic = topic
        self.metadata = {}

        client_ready_event = threading.Event()

        self.control_task = ControlListener(client_ready_event)
        self.control_task.start()
        self.control_port = self.control_task.port

        self.new_client()

        client_ready_event.wait()
        client_ready_event.clear()

    def publish(self, data, uuid=None):
        jdata = json.dumps(data)
        uuid = uuid or ''
        self.socket.send_multipart([self.topic.encode(self.encoding),
                                    uuid.encode(self.encoding),
                                    jdata.encode(self.encoding)])

    def publish_data(self, data, uuid, meta, arrays):
        jdata = json.dumps(data)
        uuid = uuid or ''
        jmeta = json.dumps(meta)
        self.socket.send_multipart([self.topic.encode(self.encoding),
                                    uuid.encode(self.encoding),
                                    jdata.encode(self.encoding),
                                    jmeta.encode(self.encoding),
                                    *arrays])

    def add_metadata(self, new_metadata, uuid=None):
        data = {'metadata': new_metadata}
        self.publish(data, uuid)

    def store(self, loop_indices, ids_values, uuid):
        data = {'data': {'values': ids_values,
                         'indices': loop_indices}}
        self.publish(data, uuid)

    def save_metadata(self, metadata, uuid=None):
        self.add_metadata(metadata, uuid)

    def finalize(self, uuid=None):
        self.publish({'finalize': True}, uuid)

    def new_client(self, name=None):
        this_dir, this_filename = os.path.split(__file__)
        client = os.path.join(this_dir, 'RemotePlotClient.py')
        print(client)
        args = ['python',
                client,
                self.topic,
                str(self.port),
                str(self.control_port)]

        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(args, creationflags=DETACHED_PROCESS)

    def clear(self):
        self.publish({'clear_plot': True})

    def add(self, *args, x=None, y=None, z=None,
            subplot=1, name=None, title=None, position=None,
            relativeto=None, xlabel=None, ylabel=None, zlabel=None,
            xunit=None, yunit=None, zunit=None, **kwargs):

        if x is not None:
            kwargs['x'] = x
        if y is not None:
            kwargs['y'] = y
        if z is not None:
            kwargs['z'] = z

        self.expand_trace(args, kwargs)

        x = kwargs.get('x', None)
        y = kwargs.get('y', None)
        z = kwargs.get('z', None)

        uuid = None

        arguments = {'subplot': subplot,
                     'title': title,
                     'position': position,
                     'relativeto': relativeto}

        if x:
            if isinstance(x, DataArray):
                snap = x.snapshot()
                uuid = x.data_set.uuid
                # if (~np.isnan(x.ndarray)).any():
                #     arguments['x_array'] = pickle.dumps(x.ndarray, protocol=4)
                arguments['x_info'] = snap
                arguments['x_info']['label'] = snap.get('label', xlabel)
                arguments['x_info']['unit'] = snap.get('unit', xunit)
                arguments['x_info']['location'] = x.data_set.location
                arguments['name'] = name or snap.get('array_id', None)
            else:
                print('Fail on x')
        if y:
            if isinstance(y, DataArray):
                snap = y.snapshot()
                uuid = y.data_set.uuid
                # if (~np.isnan(y.ndarray)).any():
                #     arguments['y_array'] = pickle.dumps(y.ndarray, protocol=4)
                arguments['y_info'] = snap
                # arguments['y_info']['uuid'] = y.data_set.uuid
                arguments['y_info']['label'] = snap.get('label', ylabel)
                arguments['y_info']['unit'] = snap.get('unit', yunit)
                arguments['y_info']['location'] = x.data_set.location
                arguments['name'] = name or snap.get('array_id', None)
            else:
                print('Fail on y')
        if z:
            if isinstance(z, DataArray):
                snap = z.snapshot()
                uuid = z.data_set.uuid
                # if (~np.isnan(z.ndarray)).any():
                #     arguments['z_array'] = pickle.dumps(z.ndarray, protocol=4)
                arguments['z_info'] = snap
                # arguments['z_info']['uuid'] = z.data_set.uuid
                arguments['z_info']['label'] = snap.get('label', zlabel)
                arguments['z_info']['unit'] = snap.get('unit', zunit)
                arguments['z_info']['location'] = x.data_set.location
                arguments['name'] = name or snap.get('array_id', None)
            else:
                print('Fail on z')
        # print('uuid:', uuid)

        meta = []
        arrays = []

        for arr in [x, y, z]:
            if arr is not None:
                if (~np.isnan(arr.ndarray)).any():
                    arrays.append(arr.ndarray)
                    meta.append({'array_id': arr.array_id,
                                 'shape': arr.ndarray.shape,
                                 'dtype': str(arr.ndarray.dtype)})

        if len(arrays) > 0:
            self.publish_data({'add_plot': arguments},
                              uuid, meta, arrays)
        else:
            self.publish({'add_plot': arguments}, uuid)

    def expand_trace(self, args, kwargs):
        """
        Complete the x, y (and possibly z) data definition for a trace.

        Also modifies kwargs in place so that all the data needed to fully specify the
        trace is present (ie either x and y or x and y and z)

        Both ``__init__`` (for the first trace) and the ``add`` method support multiple
        ways to specify the data in the trace:

        As \*args:
            - ``add(y)`` or ``add(z)`` specify just the main 1D or 2D data, with the setpoint
              axis or axes implied.
            - ``add(x, y)`` or ``add(x, y, z)`` specify all axes of the data.
        And as \*\*kwargs:
            - ``add(x=x, y=y, z=z)`` you specify exactly the data you want on each axis.
              Any but the last (y or z) can be omitted, which allows for all of the same
              forms as with \*args, plus x and z or y and z, with just one axis implied from
              the setpoints of the z data.

        This method takes any of those forms and converts them into a complete set of
        kwargs, containing all of the explicit or implied data to be used in plotting this trace.

        Args:
            args (Tuple[DataArray]): positional args, as passed to either ``__init__`` or ``add``
            kwargs (Dict(DataArray]): keyword args, as passed to either ``__init__`` or ``add``.
                kwargs may contain non-data items in keys other than x, y, and z.

        Raises:
           ValueError: if the shape of the data does not match that of args
           ValueError: if the data is provided twice
        """
        # TODO(giulioungaretti): replace with an explicit version:
        # return the new kwargs  instead of modifying in place
        # TODO this should really be a static method
        if args:
            if hasattr(args[-1][0], '__len__'):
                # 2D (or higher... but ignore this for now)
                # this test works for both numpy arrays and bare sequences
                axletters = 'xyz'
                ndim = 2
            else:
                axletters = 'xy'
                ndim = 1

            if len(args) not in (1, len(axletters)):
                raise ValueError('{}D data needs 1 or {} unnamed args'.format(
                    ndim, len(axletters)))

            arg_axletters = axletters[-len(args):]

            for arg, arg_axletters in zip(args, arg_axletters):
                # if arg_axletters in kwargs:
                #     raise ValueError(arg_axletters + ' data provided twice')
                kwargs[arg_axletters] = arg

        # reset axletters, we may or may not have found them above
        axletters = 'xyz' if 'z' in kwargs else 'xy'
        main_data = kwargs[axletters[-1]]
        if hasattr(main_data, 'set_arrays'):
            num_axes = len(axletters) - 1
            # things will probably fail if we try to plot arrays of the
            # wrong dimension... but we'll give it a shot anyway.
            set_arrays = main_data.set_arrays[-num_axes:]
            # for 2D: y is outer loop, which is earlier in set_arrays,
            # and x is the inner loop... is this the right convention?
            # Merlin: Not in my view, I step on x-axis and do many
            #         y-sweeps, thus removed this reversing here.
            set_axletters = axletters[:-1]
            for axletter, set_array in zip(set_axletters, set_arrays):
                if axletter not in kwargs:
                    kwargs[axletter] = set_array

    def set_title(self, title):
        self.publish({'set_title': title})

    def set_cmap(self, cmap):
        self.publish({'set_cmap': cmap})

    def save(self, filename=None):
        self.publish({'save_screenshot': str(filename)})
        print('Should save a screenshot of the plot now')

    def set_xlabel(self, label, subplot=1):
        print('Should set the x-label of a subplot now')

    def set_ylabel(self, label, subplot=1):
        print('Should set the y-label of a subplot now')

    def set_geometry(self, height, width, x0, y0):
        # like other qt takes it:
        print('Should set the geometry of the window now')

    def close(self):
        self.publish({'close_client': True})
        print('Should close the plot window now')