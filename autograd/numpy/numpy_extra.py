from copy import copy
import operator as op
from autograd.core import Node, primitive as P, swap_args
from . import numpy_wrapper as anp

take = P(lambda A, idx : A[idx])
def make_grad_take(ans, A, idx):
    shape = A.shape
    return lambda g : untake(g, idx, shape)
take.defgrad(make_grad_take)

untake = P(lambda x, idx, shape : SparseArray(shape, idx, x))
untake.defgrad(lambda ans, x, idx, shape : lambda g : take(g, idx))

class ArrayNode(Node):
    __slots__ = []
    __getitem__ = take
    # Constants w.r.t float data just pass though
    shape = property(lambda self: self.value.shape)
    ndim  = property(lambda self: self.value.ndim)
    size  = property(lambda self: self.value.size)
    T = property(lambda self: anp.transpose(self))

    __neg__ = P(op.neg)

    # Binary ops already wrapped by autograd.numpy.ndarray
    dot = anp.ndarray.dot.__func__
    __add__  = anp.ndarray.__add__.__func__
    __sub__  = anp.ndarray.__sub__.__func__
    __mul__  = anp.ndarray.__mul__.__func__
    __pow__  = anp.ndarray.__pow__.__func__
    __div__  = anp.ndarray.__div__.__func__
    __radd__ = anp.ndarray.__radd__.__func__
    __rsub__ = anp.ndarray.__rsub__.__func__
    __rmul__ = anp.ndarray.__rmul__.__func__
    __rpow__ = anp.ndarray.__rpow__.__func__
    __rdiv__ = anp.ndarray.__rdiv__.__func__

Node.type_mappings[anp.ndarray] = ArrayNode
ArrayNode.__dict__['__neg__'].defgrad(lambda ans, x : op.neg)

# These numpy.ndarray methods are just refs to an equivalent numpy function
nondiff_methods = ['all', 'any', 'argmax', 'argmin', 'argpartition',
                   'argsort', 'max', 'min', 'nonzero', 'searchsorted',
                   'round', ]
diff_methods = ['clip', 'compress', 'cumprod', 'cumsum', 'diagonal',
                'mean', 'prod', 'ptp', 'ravel', 'repeat',
                'reshape', 'squeeze', 'std', 'sum', 'swapaxes', 'take',
                'trace', 'transpose', 'var']
for name in nondiff_methods + diff_methods:
    setattr(ArrayNode, name, anp.__dict__[name])

# ----- Special sparse array type for efficient grads through indexing -----

class SparseArray(object):
    __array_priority__ = 150.0
    def __init__(self, shape, idx, val):
        self.shape = shape
        self.idx = idx
        self.val = val

    def __add__(self, other):
        array = anp.zeros(self.shape) if other is 0 else copy(other)
        array[self.idx] += self.val
        return array

    def __radd__(self, other):
        return self.__add__(other)

class SparseArrayNode(Node):
    __slots__ = []
    __add__  = P(SparseArray.__add__)
    __radd__ = P(SparseArray.__radd__)
Node.type_mappings[SparseArray] = SparseArrayNode

I = lambda x : x
SparseArrayNode.__dict__['__add__'].defgrad(lambda ans, x, y : I)
SparseArrayNode.__dict__['__add__'].defgrad(lambda ans, x, y : I, argnum=1)
SparseArrayNode.__dict__['__radd__'].grads = swap_args(SparseArrayNode.__dict__['__add__'].grads)
