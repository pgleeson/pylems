"""
Base class for runnable components.

@author: Gautham Ganapathy
@organization: Textensor (http://textensor.com)
@contact: gautham@textensor.com, gautham@lisphacker.org
"""

from lems.base.base import LEMSBase
from lems.base.util import Stack
from lems.base.errors import SimBuildError
from lems.sim.recording import Recording

import ast
import sys

from math import *

#import math

#class Ex1(Exception):
#    pass

#def exp(x):
#    try:
#        return math.exp(x)
#    except Exception as e:
#        print('ERROR performing exp({0})'.format(x))
#        raise Ex1()

class Reflective(object):
    def __init__(self):
        self.instance_variables = []
        self.derived_variables = []
        self.array = []

    #@classmethod
    def add_method(self, method_name, parameter_list, statements):
        code_string = 'def __generated_function__'
        if parameter_list == []:
            code_string += '():\n'
        else:
            code_string += '(' + parameter_list[0]
            for parameter in parameter_list[1:]:
                code_string += ', ' + parameter
            code_string += '):\n'

        if statements == []:
            code_string += '    pass'
        else:
            for statement in statements:
                code_string += '    ' + statement + '\n'

        g = globals()
        l = locals()
        exec(compile(ast.parse(code_string), '<unknown>', 'exec'), g, l)

        #setattr(cls, method_name, __generated_function__)
        self.__dict__[method_name] = l['__generated_function__']
        del l['__generated_function__']

    def add_instance_variable(self, variable, initial_value):
        self.instance_variables.append(variable)

        code_string = 'self.{0} = {1}\nself.{0}_shadow = {1}'.format(\
            variable, initial_value)
        exec(compile(ast.parse(code_string), '<unknown>', 'exec'))

    def add_derived_variable(self, variable):
        self.derived_variables.append(variable)

        code_string = 'self.{0} = {1}\nself.{0}_shadow = {1}'.format(\
            variable, 0)
        exec(compile(ast.parse(code_string), '<unknown>', 'exec'))

    def add_text_variable(self, variable, value):
        self.__dict__[variable] = value

    def __getitem__(self, key):
        return self.array[key]

    def __setitem__(self, key, val):
        self.array[key] = val

class Regime:
    def __init__(self, name):
        self.name = name
        self.update_state_variables = None
        self.update_derived_variables = None
        self.run_startup_event_handlers = None
        self.run_preprocessing_event_handlers = None
        self.run_postprocessing_event_handlers = None
        self.update_kinetic_scheme = None

class Runnable(Reflective):
    def __init__(self, id_, component, parent = None):
        Reflective.__init__(self)

        self.id = id_
        self.component = component
        self.parent = parent

        self.time_step = 0
        self.time_completed = 0
        self.time_total = 0

        self.plastic = True

        self.state_stack = Stack()

        self.children = {}

        self.recorded_variables = {}

        self.event_out_ports = []
        self.event_in_ports = []

        self.event_out_callbacks = {}
        self.event_in_counters = {}

        self.attachments = {}

        self.new_regime = ''
        self.current_regime = ''
        self.last_regime = ''
        self.regimes = {}

    def add_child(self, id_, runnable):
        #self.children[id] = runnable
        self.children[runnable.id] = runnable

        self.__dict__[id_] = runnable
        self.__dict__[runnable.id] = runnable

        runnable.configure_time(self.time_step, self.time_total)

    def add_child_to_group(self, group_name, child):
        if group_name not in self.__dict__:
            self.__dict__[group_name] = []
        self.__dict__[group_name].append(child)

    def make_attachment(self, type_, name):
        self.attachments[type_] = name
        self.__dict__[name] = []

    def add_attachment(self, runnable):
        name = self.attachments[runnable.component.component_type]
        runnable.id = runnable.id + str(len(self.__dict__[name]))
        self.__dict__[name].append(runnable)

    def add_event_in_port(self, port):
        self.event_in_ports.append(port)
        if port not in self.event_in_counters:
            self.event_in_counters[port] = 0

    def inc_event_in(self, port):
        self.event_in_counters[port] += 1

    def add_event_out_port(self, port):
        self.event_out_ports.append(port)
        if port not in self.event_out_callbacks:
            self.event_out_callbacks[port] = []

    def register_event_out_link(self, port, runnable, remote_port):
        self.event_out_callbacks[port].append((runnable, remote_port))

    def register_event_out_callback(self, port, callback):
        if port in self.event_out_callbacks:
            self.event_out_callbacks[port].append(callback)
        else:
            raise SimBuildError('No event out port \'{0}\' in '
                                'component \'{1}\''.format(port, self.id))

    def add_regime(self, regime):
        self.regimes[regime.name] = regime

    def resolve_path(self, path):
        if path == '':
            return self
        if path[0] == '/':
            return self.parent.resolve_path(path)
        elif path.find('../') == 0:
            return self.parent.resolve_path(path[3:])
        elif path.find('..') == 0:
            return self.parent
        else:
            if path.find('/') >= 1:
                (child, new_path) = path.split('/', 1)
            else:
                child = path
                new_path = ''

            idxbegin = child.find('[')
            idxend = child.find(']')
            if idxbegin != 0 and idxend > idxbegin:
                idx = int(child[idxbegin+1:idxend])
                child = child[:idxbegin]
            else:
                idx = -1

            if child in self.children:
                childobj = self.children[child]
                if idx != -1:
                    childobj = childobj.array[idx]
            elif child in self.component.context.parameters:
                ctx = self.component.context
                p = ctx.parameters[child]
                return self.resolve_path('../' + p.value)
            else:
                raise SimBuildError('Unable to find child \'{0}\' in '
                                    '\'{1}\''.format(child, self.id))

            if new_path == '':
                return childobj
            else:
                return childobj.resolve_path(new_path)

    def add_variable_recorder(self, recorder):
        self.add_variable_recorder2(recorder, recorder.quantity)

    def add_variable_recorder2(self, recorder, path):
        if path[0] == '/':
            self.parent.add_variable_recorder2(recorder, path)
        elif path.find('../') == 0:
            self.parent.add_variable_recorder2(recorder, path[3:])
        elif path.find('/') >= 1:
            (child, new_path) = path.split('/', 1)

            idxbegin = child.find('[')
            idxend = child.find(']')
            if idxbegin != 0 and idxend > idxbegin:
                idx = int(child[idxbegin+1:idxend])
                child = child[:idxbegin]
            else:
                idx = -1

            if child in self.children:
                childobj = self.children[child]
                if idx == -1:
                    childobj.add_variable_recorder2(recorder, new_path)
                else:
                    childobj.array[idx].add_variable_recorder2(recorder, new_path)
            else:
                raise SimBuildError('Unable to find child \'{0}\' in '
                                    '\'{1}\''.format(child, self.id))
        else:
            self.recorded_variables[path] = Recording(recorder)


    def configure_time(self, time_step, time_total):
        self.time_step = time_step
        self.time_total = time_total

        for cn in self.children:
            self.children[cn].configure_time(self.time_step, self.time_total)

        for c in self.array:
            c.configure_time(self.time_step, self.time_total)

        for type_ in self.attachments:
            components = self.__dict__[self.attachments[type_]]
            for component in components:
                component.configure_time(self.time_step, self.time_total)


    def reset_time(self):
        self.time_completed = 0

        for cid in self.children:
            self.children[cid].reset_time()

        for c in self.array:
            c.reset_time()

        for type_ in self.attachments:
            components = self.__dict__[self.attachments[type_]]
            for component in components:
                component.reset_time()

    def single_step(self, dt):
        #return self.single_step2(dt)

        # For debugging
        try:
            return self.single_step2(dt)
        #except Ex1 as e:
        #    print self.rate
        #    print self.midpoint
        #    print self.scale
        #    print self.parent.parent.parent.parent.v
        #    # rate * exp((v - midpoint)/scale)
        #    sys.exit(0)
        except Exception as e:
            r = self
            name = r.id
            while r.parent:
                r = r.parent
                name = "{0}.{1}".format(r.id, name)

            print("Error in '{0} ({2})': {1}".format(name, e,
                                                     self.component.component_type))
            print(type(e))
            keys = self.__dict__.keys()
            keys.sort()
            for k in keys:
                print('{0} -> {1}'.format(k, self.__dict__[k]))
            print('')
            print('')

            if isinstance(e, ArithmeticError):
                print(('This is an arithmetic error. Consider reducing the '
                       'integration time step.'))

            sys.exit(0)

    def single_step2(self, dt):
        for cid in self.children:
            self.children[cid].single_step(dt)

        for child in self.array:
            child.single_step(dt)

        for type_ in self.attachments:
            components = self.__dict__[self.attachments[type_]]
            for component in components:
                component.single_step(dt)

        if self.new_regime != '':
            self.current_regime = self.new_regime
            self.new_regime = ''

        self.update_kinetic_scheme(self, dt)

        if self.time_completed == 0:
            self.run_startup_event_handlers(self)

        self.run_preprocessing_event_handlers(self)
        self.update_shadow_variables()

        self.update_derived_variables(self)
        self.update_shadow_variables()

        self.update_state_variables(self, dt)
        self.update_shadow_variables()

        self.run_postprocessing_event_handlers(self)
        self.update_shadow_variables()

        if self.current_regime != '':
            regime = self.regimes[self.current_regime]

            regime.update_kinetic_scheme(self, dt)

            #if self.time_completed == 0:
            #    self.run_startup_event_handlers(self)

            regime.run_preprocessing_event_handlers(self)
            self.update_shadow_variables()

            regime.update_derived_variables(self)
            self.update_shadow_variables()

            regime.update_state_variables(self, dt)
            self.update_shadow_variables()

            regime.run_postprocessing_event_handlers(self)
            self.update_shadow_variables()

        self.record_variables()

        self.time_completed += dt#self.time_step
        if self.time_completed >= self.time_total:
            return 0
        else:
            return dt#self.time_step


    def record_variables(self):
        for variable in self.recorded_variables:
            self.recorded_variables[variable].add_value(\
                self.time_completed, self.__dict__[variable])

    def push_state(self):
        vars = []
        for varname in self.instance_variables:
            vars += [self.__dict__[varname],
                     self.__dict__[varname + '_shadow']]
        self.state_stack.push(vars)

        for cid in self.children:
            self.children[cid].push_state()

        for c in self.array:
            c.push_state()

    def pop_state(self):
        vars = self.state_stack.pop()
        for varname in self.instance_variables:
            self.__dict_[varname] = vars[0]
            self.__dict_[varname + '_shadow'] = vars[1]
            vars = vars[2:]

        for cid in self.children:
            self.children[cid].pop_state()

        for c in self.array:
            c.pop_state()

    def update_shadow_variables(self):
        if self.plastic:
            for var in self.instance_variables:
                self.__dict__[var + '_shadow'] = self.__dict__[var]
            for var in self.derived_variables:
                self.__dict__[var + '_shadow'] = self.__dict__[var]
