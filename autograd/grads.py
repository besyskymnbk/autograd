import numpy as np
import operator as op
from functools import partial
from core import primitive, getval, untake
import scipy.stats as sps

P = primitive

# ----- Operator gradients -----
I = lambda x : x # Identity operator
neg = P(op.neg, lambda ans, x    : [op.neg])
add = P(op.add, lambda ans, x, y : unbroadcast(ans, x, y, [I, I]))
mul = P(op.mul, lambda ans, x, y : unbroadcast(ans, x, y, [lambda g : y * g, lambda g : x * g]))
sub = P(op.sub, lambda ans, x, y : unbroadcast(ans, x, y, [I, op.neg]))
div = P(op.div, lambda ans, x, y : unbroadcast(ans, x, y, [lambda g : g / y, lambda g : - g * x / y**2]))
pow = P(op.pow, lambda ans, x, y : unbroadcast(ans, x, y, [lambda g : g * y * x ** (y - 1),
                                                              lambda g : g * np.log(x) * x ** y]))
isarray = lambda x : isinstance(getval(x), np.ndarray)
isfloat = lambda x : isinstance(getval(x), float)

def unbroadcast(ans, x, y, funs):
    return [unbroadcast_fun(ans, x, funs[0]),
            unbroadcast_fun(ans, y, funs[1])]

def unbroadcast_fun(ans, x, fun):
    if isfloat(x) and isarray(ans):
        return lambda g : np.sum(fun(g))
    elif isarray(x):
        shape = x.shape
        def new_fun(g):
            result = fun(g)
            while result.ndim > len(shape):
                result = np.sum(result, axis=0)
            for axis, size in enumerate(shape):
                if size is 1:
                    result = np.sum(result, axis, keepdims=True)
            return result
        return new_fun
    else:
        return fun

# ----- Numpy gradients -----

np.abs    = P(np.abs,    lambda ans, x : [lambda g : np.sign(x) * g])
np.exp    = P(np.exp,    lambda ans, x : [lambda g : ans * g])
np.log    = P(np.log,    lambda ans, x : [lambda g : g / x])
np.sin    = P(np.sin,    lambda ans, x : [lambda g : g * np.cos(x)])
np.cos    = P(np.cos,    lambda ans, x : [lambda g : - g * np.sin(x)])
np.tan    = P(np.tan,    lambda ans, x : [lambda g : g / np.cos(x) **2])
np.sinh   = P(np.sinh,   lambda ans, x : [lambda g : g * np.cosh(x)])
np.cosh   = P(np.cosh,   lambda ans, x : [lambda g : g * np.sinh(x)])
np.tanh   = P(np.tanh,   lambda ans, x : [lambda g : g / np.cosh(x) **2])
np.square = P(np.square, lambda ans, x : [lambda g : g * 2 * x])
np.sqrt   = P(np.sqrt,   lambda ans, x : [lambda g : g * 0.5 * x**-0.5])
np.sign   = P(np.sign,   lambda ans, x : [lambda g : 0.0])
np.full   = P(np.full,   lambda ans, shape, fill_value : [None, lambda g :  np.sum(g)])
np.reshape     = P(np.reshape,     lambda ans, x, shape, order=None : [lambda g : np.reshape(g, x.shape, order=order)])
np.ravel       = P(np.ravel,       lambda ans, x,        order=None : [lambda g : np.reshape(g, x.shape, order=order)])
np.expand_dims = P(np.expand_dims, lambda ans, x, axis              : [lambda g : np.squeeze(g, axis)])
np.squeeze     = P(np.squeeze,     lambda ans, x, axis              : [lambda g : np.repeat(g, x.shape[axis], axis)])
np.repeat      = P(np.repeat,      lambda ans, x, shape, axis       : [lambda g : np.sum(g, axis, keepdims=True)])
np.transpose   = P(np.transpose,   lambda ans, x                    : [lambda g : np.transpose(g)])
np.split       = P(np.split,       lambda ans, x, idxs, axis=0      : [lambda g : np.concatenate(g, axis=axis)])
np.roll        = P(np.roll,        lambda ans, x, shift, axis=None  : [lambda g : np.roll(g, -shift, axis=axis)])
np.diag        = P(np.diag,        lambda ans, x                    : [lambda g : np.diag(g)])
np.trace       = P(np.trace,       lambda ans, x                    : [lambda g : g * np.eye(x.shape[0])])
np.linalg.inv  = P(np.linalg.inv,  lambda ans, x                    : [lambda g : -np.dot(np.dot(ans.T, g), ans.T)])
np.linalg.det  = P(np.linalg.det,  lambda ans, x                    : [lambda g : g * ans * np.linalg.inv(x).T])

# ----- Scipy gradients -----
sps.norm.cdf   = P(sps.norm.cdf, lambda ans, x, loc=0.0, scale=1.0 : [lambda g : g * (1./(np.sqrt(2.0*np.pi)*scale)) *np.exp(-((x-loc)**2.0)/(2.0*(scale**2.)))])


def repeat_to_match_shape(x, axis, keepdims):
    """Returns a function that repeats an array along axis to get a given shape.
       Also returns the number of repetitions of the array."""
    if not isarray(x):
        return I, 1
    shape = x.shape
    if axis is None:
        return lambda g : np.full(shape, g), np.prod(shape)
    else:
        if keepdims:
            return lambda g : np.repeat(g, shape[axis], axis), shape[axis]
        else:
            return lambda g : np.repeat(np.expand_dims(g, axis),
                                         shape[axis], axis), shape[axis]

def make_grad_np_sum(ans, x, axis=None, keepdims=False):
    repeater, _ = repeat_to_match_shape(x, axis, keepdims)
    return [repeater]
np.sum = P(np.sum, make_grad_np_sum)

def make_grad_np_mean(ans, x, axis=None, keepdims=False):
    repeater, num_reps = repeat_to_match_shape(x, axis, keepdims)
    return [lambda g: repeater(g) / num_reps]
np.mean = P(np.mean, make_grad_np_mean)

def make_grad_chooser(ans, x, axis=None, keepdims=None):
    """Builds gradient of functions that choose a single item, such as min or max."""
    repeater, _ = repeat_to_match_shape(x, axis, keepdims)
    argmax_locations = x == repeater(ans)
    return [lambda g: repeater(g) * argmax_locations]
np.max = P(np.max, make_grad_chooser)
np.min = P(np.min, make_grad_chooser)

def make_grad_np_dot(ans, A, B):
    def grad_np_dot_A(g):
        if B.ndim is 2:
            return np.dot(g, B.T)
        elif A.ndim is 2:
            return np.outer(g, B)
        else:
            return g * B
    def grad_np_dot_B(g):
        if A.ndim is 2:
            return np.dot(A.T, g)
        elif B.ndim is 2:
            return np.outer(A, g)
        else:
            return g * A
    return [grad_np_dot_A, grad_np_dot_B]
np.dot = P(np.dot, make_grad_np_dot)

def make_grad_np_concatenate(ans, arr_list, axis=0):
    def grad_np_concatenate(g):
        idxs = np.cumsum([a.shape[axis] for a in getval(arr_list)[:-1]])
        return np.split(g, idxs, axis=axis)
    return [grad_np_concatenate]
np.concatenate = P(np.concatenate, make_grad_np_concatenate)

# ----- Special list constructor -----

class ArgnumGrad(object):
    def __init__(self, fun_with_argnum):
        self.fun = fun_with_argnum
    def __getitem__(self, argnum):
        return partial(self.fun, argnum)

def kylist(*args):
    return list(args)
kylist = primitive(kylist, lambda ans, *args : ArgnumGrad(lambda argnum, g : g[argnum]))

# Wrap the concatenation function to automatically wrap the list into a kylist.
unwrapped_np_concatenate = np.concatenate
def concatwrapper(*args, **kwargs):
    args = (kylist(*(args[0])),) + args[1:]
    return unwrapped_np_concatenate(*args, **kwargs)
np.concatenate = concatwrapper

def make_grad_np_array(ans, arr_list, axis=0):
    def grad_np_array(g):
        return g
    return [grad_np_array]
np.array = P(np.array, make_grad_np_array)

unwrapped_np_array = np.array
def array_wrapper(arg, *args, **kwargs):
    arg = recursive_kylist(*arg)
    return unwrapped_np_array(arg, *args, **kwargs)
np.array = array_wrapper

def recursive_kylist(*args):
    args = list(args)
    for i, arg in enumerate(args):
        if isinstance(arg, list):
            args[i] = recursive_kylist(*arg)
    return kylist(*args)
