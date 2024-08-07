from datetime import datetime
from multiprocessing import Array
from queue import Empty, Full
import time

# except AttributeError:
# from multiprocessing import Queue
import numpy as np

# try:
from extra.portable_queue import PortableQueue  # as Queue


class ArrayView:
    def __init__(self, array, max_bytes, dtype, el_shape, i_item=0):
        self.dtype = dtype
        self.el_shape = el_shape
        self.nbytes_el = self.dtype.itemsize * np.product(self.el_shape)
        self.n_items = int(np.floor(max_bytes / self.nbytes_el))
        self.total_shape = (self.n_items,) + self.el_shape
        self.idx_item = i_item
        self.view = np.frombuffer(array, dtype, np.product(self.total_shape)).reshape(
            self.total_shape
        )

    def __eq__(self, other):
        """Overrides the default implementation"""
        if isinstance(self, other.__class__):
            return self.el_shape == other.el_shape and self.dtype == other.dtype
        return False

    def push(self, element):
        self.view[self.idx_item, ...] = element
        idx_inserted = self.idx_item
        self.idx_item = (self.idx_item + 1) % self.n_items
        # a tuple is returned to maximise performance
        return self.dtype, self.el_shape, idx_inserted

    def pop(self, i_item):
        return self.view[i_item, ...]

    def fits(self, item):
        if isinstance(item, np.ndarray):
            return item.dtype == self.dtype and item.shape == self.el_shape
        return (
            item[0] == self.dtype
            and item[1] == self.el_shape
            and item[2] < self.n_items
        )


class ArrayQueue:
    """A drop-in replacement for the multiprocessing queue, usable
    only for numpy arrays, which removes the need for pickling and
    should provide higher speeds and lower memory usage

    """

    def __init__(self, max_mbytes=50):
        self.maxbytes = int(max_mbytes * 1000000)
        self.array = Array("c", self.maxbytes)
        self.view = None
        self.queue = PortableQueue()
        self.read_queue = PortableQueue()
        self.last_item = 0

    def check_full(self):
        while True:
            try:
                self.last_item = self.read_queue.get(timeout=0.00001)
            except Empty:
                break
        if self.view.idx_item == self.last_item:
            raise Full(
                "Queue of length {} full when trying to insert {},"
                " last item read was {}".format(
                    self.view.n_items, self.view.idx_item, self.last_item
                )
            )

    def put(self, element):
        if self.view is None or not self.view.fits(element):
            self.view = ArrayView(
                self.array.get_obj(), self.maxbytes, element.dtype, element.shape
            )
            self.last_item = 0
        else:
            self.check_full()

        # qitem is a triple of (dtype, el_shape, idx)
        qitem = self.view.push(element)

        self.queue.put(qitem)

    def get(self, **kwargs):

        # This should get the (dtype, el_shape, idx) triple
        aritem = self.queue.get(**kwargs)

        if self.view is None or not self.view.fits(aritem):
            # Reset ArrayQueue if it doesn't exist, or if the obtained item doesn't match
            self.view = ArrayView(self.array.get_obj(), self.maxbytes, *aritem)

        # Adds to queue of items popped.
        self.read_queue.put(aritem[2])

        # Return item
        return self.view.pop(aritem[2])

    def clear(self):
        """Empties the queue without the need to read all the existing
        elements

        :return: nothing
        """
        self.view = None
        while True:
            try:
                _ = self.queue.get_nowait()
            except Empty:
                break
        while True:
            try:
                _ = self.read_queue.get_nowait()
            except Empty:
                break

        self.last_item = 0

    def empty(self):
        return self.queue.empty()

    def qsize(self):
        return self.queue.qsize()


class TimestampedArrayQueue(ArrayQueue):
    """A small extension to support timestamps saved alongside arrays"""

    def put(self, element, TTL_on=False):
        if self.view is None or not self.view.fits(element):
            self.view = ArrayView(
                self.array.get_obj(), self.maxbytes, element.dtype, element.shape
            )
        else:
            self.check_full()

        # element goes into memory mapped queue. Returns qitem, which is (dtype, shape, idx) tuple
        dtype_shape_idx = self.view.push(element)
        timestamp = time.time()

        # These small items go into the standard multiprocessor queue.
        self.queue.put((timestamp, TTL_on, dtype_shape_idx))

    def get(self, **kwargs):
        # Get timestamp and index from a conventional multiprocessor queue. This will
        # throw the usual queue.Empty exception if there are no items
        timestamp, TTL_on, dtype_shape_idx = self.queue.get(**kwargs)
        if self.view is None or not self.view.fits(dtype_shape_idx):
            self.view = ArrayView(self.array.get_obj(), self.maxbytes, *dtype_shape_idx)
        self.read_queue.put(dtype_shape_idx[2])
        return timestamp, self.view.pop(dtype_shape_idx[2]), TTL_on

