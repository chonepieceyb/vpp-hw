import argparse
import dataclasses
import json
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field, fields
from datetime import datetime
from functools import reduce
from itertools import product
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple, Union, cast

from sqlalchemy import DDL, Boolean, Column, DateTime, Float, Identity, Integer, MetaData, String, Table, create_engine, func, insert, text
from sqlalchemy.sql.ddl import CreateColumn


class CommandLineTool:
    def __init__(self, command: Iterable[str], verbose: bool = False) -> None:
        self._command = tuple(command)
        self._verbose = verbose

    @property
    def command(self) -> Tuple[str, ...]:
        return self._command

    @property
    def verbose(self) -> bool:
        return self._verbose

    class InvocationError(RuntimeError):
        def __init__(self, error: subprocess.CalledProcessError) -> None:
            lines = [
                f'Tool invocation failed with code {error.returncode}',
                f'command: {error.cmd}',
            ]
            stdout = CommandLineTool._try_decode(error.stdout)
            if stdout:
                lines.append(f'stdout:\n{stdout}')
            stderr = CommandLineTool._try_decode(error.stderr)
            if stderr:
                lines.append(f'stderr:\n{stderr}')
            super().__init__('\n'.join(lines))

    def invoke(self, *args: str, **kwargs: Any) -> subprocess.CompletedProcess:
        """
        Run tool with the given arguments and return the standard error.

        :param args: Arguments to pass to the tool
        :param kwargs: Keyword arguments to pass to `subprocess.run`

        :returns: Completed process object
        """
        return self._invoke(args, **kwargs)

    def __call__(self, *args: str, **kwargs: Any) -> Union[str, bytes]:
        """
        Run tool with the given arguments.

        :param args: Arguments to pass to the tool
        :param kwargs: Keyword arguments to pass to `subprocess.run`

        :returns: Standard output of the command
        """
        return self._try_decode(self._invoke(args, **kwargs).stdout)

    def _invoke(self, args: Iterable[str], **kwargs: Any) -> subprocess.CompletedProcess:
        command = [*self._command, *args]
        kwargs = {
            'capture_output': True,
            'check': True,
            **kwargs,
        }
        try:
            if self._verbose:
                print('+ ' + shlex.join(command), file=sys.stderr)
            process = subprocess.run(command, **kwargs)
            if self._verbose:
                for prefix, output in zip(('E ', '* '), map(self._try_decode, (process.stderr, process.stdout))):
                    if not output:
                        continue
                    if isinstance(output, str):
                        print('\n'.join(prefix + line for line in output.splitlines()), file=sys.stderr)
                    else:
                        print(f'{prefix} <binary>', file=sys.stderr)
            return process
        except subprocess.CalledProcessError as e:
            raise self.InvocationError(e) from e

    @classmethod
    def _try_decode(cls, data: Union[str, bytes]) -> Union[str, bytes]:
        if isinstance(data, str):
            return data
        try:
            return data.decode()  # type: ignore
        except UnicodeDecodeError:
            return data

    _CONTROL_SEQUENCE_PATTERN = re.compile(r'\x1b\[[0-9;]*[mGK]')

    @classmethod
    def _remove_control_chars(cls, s: str) -> str:
        return cls._CONTROL_SEQUENCE_PATTERN.sub('', s)

    _SLASH_PATTERN = re.compile(r'\s?/\s?')
    _INVALID_SEQUENCE_PATTERN = re.compile(r'[^a-zA-Z0-9_]+')
    _SEPARATOR = '_'

    @classmethod
    def _normalize_identifier(cls, s: str) -> str:
        s = cls._SLASH_PATTERN.sub(' per ', s)
        s = cls._INVALID_SEQUENCE_PATTERN.sub(cls._SEPARATOR, s)
        s = s.strip(cls._SEPARATOR)
        s = s.lower()
        return s


class VPPCtl(CommandLineTool):
    DEFAULT_COMMAND = ('vppctl',)

    def __init__(self, command: Iterable[str] = DEFAULT_COMMAND, verbose: bool = False) -> None:
        super().__init__(command, verbose)

    def clear_runtime(self, **kwargs: Any) -> None:
        """
        Call `vppctl clear runtime`.
        """
        self._invoke(['clear', 'runtime'], **kwargs)

    def dpdk_latency_reset(self, **kwargs) -> None:
        """
        Call `vppctl dpdk latency reset`.
        """
        self._invoke(['dpdk', 'latency', 'reset'], **kwargs)

    def perfmon_start(self, bundle: Optional[str] = None, type_: Optional[str] = None, **kwargs: Any) -> None:
        """
        Call `vppctl perfmon start bundle <bundle-name> type <type>`.

        :param bundle: Bundle name
        :param type_: Type
        """
        args = ['perfmon', 'start']
        if bundle is not None:
            args += ['bundle', bundle]
        if type_ is not None:
            args += ['type', type_]
        self._invoke(args, **kwargs)

    def perfmon_stop(self, **kwargs: Any) -> None:
        """
        Call `vppctl perfmon stop`.
        """
        self._invoke(['perfmon', 'stop'], **kwargs)

    def perfmon_reset(self, **kwargs: Any) -> None:
        """
        Call `vppctl perfmon reset`.
        """
        self._invoke(['perfmon', 'reset'], **kwargs)

    @dataclass
    class DPDKInterfaceBatchConfig:
        size: int
        """Batch size of `dpdk-input`."""
        timeout: float
        """Timeout (in seconds) of `dpdk-input`."""

    @dataclass
    class DPDKBatchConfig:
        interfaces: Dict[str, 'VPPCtl.DPDKInterfaceBatchConfig'] = field(default_factory=dict)

    def set_dpdk_batchsize(
        self,
        config: Union[DPDKBatchConfig, Mapping[str, Union[DPDKInterfaceBatchConfig, Mapping[str, Any]]]],
        **kwargs: Any,
    ) -> None:
        """
        Set `dpdk-input` batching configuration with `vppctl set dpdk batchsize`.

        :param config: Configuration or mapping from interface name to the configuration
        """
        if isinstance(config, self.DPDKBatchConfig):
            config = config.interfaces
        if len(config) != 1:
            raise ValueError('config must have exactly one element')
        interface, value = next(iter(config.items()))
        if not isinstance(value, self.DPDKInterfaceBatchConfig):
            value = self.DPDKInterfaceBatchConfig(**value)
        self._invoke(
            ['set', 'dpdk', 'batchsize', interface, 'batchsize', str(value.size), 'timeout', str(value.timeout)],
            **kwargs,
        )

    @dataclass
    class NodeBatchConfig:
        size: Optional[int] = field(default=None)
        """Batch size of the node; set to `None` to not change"""
        timeout: Optional[int] = field(default=None)
        """Timeout (in us) of the node; set to `None` to not change"""

    @dataclass
    class BatchConfig:
        nodes: Dict[Union[int, str], 'VPPCtl.NodeBatchConfig'] = field(default_factory=dict)

    def set_node_batch(
        self,
        config: Union[BatchConfig, Mapping[Union[int, str], Union[NodeBatchConfig, Mapping[str, Any]]]],
        **kwargs: Any,
    ) -> None:
        """
        Set node batching configurations with `vppctl set node batch`.

        :param config: Mapping of node index or name to the configuration
        """
        args = ['set', 'node', 'batch']
        if isinstance(config, self.BatchConfig):
            config = config.nodes
        for k, c in config.items():
            if isinstance(k, int):
                args += ['index', str(k)]
            else:
                args += [str(k)]
            if not isinstance(c, self.NodeBatchConfig):
                c = self.NodeBatchConfig(**c)
            if c.size is not None:
                args += ['size', str(c.size)]
            if c.timeout is not None:
                args += ['timeout', str(c.timeout)]
        self._invoke(args, **kwargs)

    @dataclass
    class DPDKProtocolStat:
        """
        DPDK protocol-level statistics.
        """

        avg_throughput_pkt_per_s: int
        avg_lat_ns: int
        timeout_pkts: int
        total_pkts: int

    @dataclass
    class DPDKInterfaceStat:
        """
        DPDK interface-level statistics.
        """

        avg_throughput_pkt_per_s: int
        avg_lat_ns: int
        timeout_pkts: int
        total_pkts: int
        imissed: int
        protocols: Dict[int, 'VPPCtl.DPDKProtocolStat'] = field(default_factory=dict)

    @dataclass
    class DPDKStat:
        """
        DPDK statistics.
        """

        interfaces: Dict[str, 'VPPCtl.DPDKInterfaceStat'] = field(default_factory=dict)

    def show_dpdk_latency(self, **kwargs: Any) -> DPDKStat:
        """
        Call `vppctl show dpdk latency` and return the parsed output.

        :returns: Parsed output
        """
        output = self._invoke(['show', 'dpdk', 'latency'], **kwargs).stdout.decode()
        line_iterator = iter(output.strip().split('\n'))
        next(line_iterator)  # skip 'current time_diff(s): 1619'
        interfaces_data = {}
        for line in line_iterator:
            interface, *stat_parts = line.split(',')
            stat_data = {self._normalize_identifier(name): int(value) for name, value in map(lambda s: s.split(':'), stat_parts)}
            protocol = stat_data.pop('protocol_identifier', None)
            if protocol is None:
                interfaces_data[interface] = self.DPDKInterfaceStat(**stat_data)  # type: ignore
            else:
                # Interface-level stats always come before protocol-level stats, so this is safe
                interfaces_data[interface].protocols[protocol] = self.DPDKProtocolStat(**stat_data)
        return self.DPDKStat(interfaces=interfaces_data)

    @dataclass
    class PerfmonNodeStat:
        """
        Output of `vppctl show perfmon statistics` for each node.
        """

        l1i_miss_per_pkt: float
        l1d_miss_per_pkt: float
        l2_miss_per_pkt: float
        l3_miss_per_pkt: float

    @dataclass
    class PerfmonThreadStat:
        """
        Output of `vppctl show perfmon statistics` for each thread.
        """

        nodes: Dict[str, 'VPPCtl.PerfmonNodeStat'] = field(default_factory=dict)

    @dataclass
    class PerfmonStat:
        """
        Output of `vppctl show perfmon statistics`.
        """

        threads: Dict[str, 'VPPCtl.PerfmonThreadStat'] = field(default_factory=dict)

    def show_perfmon_statistics(self, include_threads: Optional[Iterable[str]] = None, **kwargs: Any) -> PerfmonStat:
        """
        Call `vppctl show perfmon statistics` and return the parsed output.

        :param include_threads: Threads to include in the output; if `None`, include all threads

        :returns: Parsed output
        """
        output = self._invoke(['show', 'perfmon', 'statistics'], **kwargs).stdout.decode()
        output = self._remove_control_chars(output)
        line_iterator = iter(output.strip().split('\n'))
        next(line_iterator)  # skip title
        next(line_iterator)  # skip header (we assume the order of stats is consistent with fields in PerfmonStat, as it is difficult to parse headers)
        thread = None
        threads_data = {}
        nodes_data = {}
        for line in line_iterator:
            if '(' in line:  # e.g. 'vpp_wk_0 (1)'
                if thread is not None and (include_threads is None or thread in include_threads):
                    threads_data[thread] = nodes_data
                thread = line.split()[0]
                nodes_data = {}
            else:
                node, *values = line.split()
                nodes_data[node] = self.PerfmonNodeStat(*map(float, values))
        if thread is not None and (include_threads is None or thread in include_threads):
            threads_data[thread] = self.PerfmonThreadStat(nodes=nodes_data)
        return self.PerfmonStat(threads=threads_data)

    @dataclass
    class RuntimeNodeStat:
        """
        Output of `vppctl show runtime` for each node.
        """

        state: str
        calls: float
        vectors: float
        suspends: float
        clocks: float
        vectors_per_call: float
        avg_dpc_per_call: float
        total_dto: float

    @dataclass
    class RuntimeVectorRateStat:
        """
        Output of `vppctl show runtime` for vector rates.
        """

        in_: float
        out: float
        drop: float
        punt: float

    @dataclass
    class RuntimeThreadStat:
        """
        Output of `vppctl show runtime` for each thread.
        """

        vector_rates: 'VPPCtl.RuntimeVectorRateStat'
        nodes: Dict[str, 'VPPCtl.RuntimeNodeStat'] = field(default_factory=dict)

    @dataclass
    class RuntimeStat:
        """
        Output of `vppctl show runtime`.
        """

        threads: Dict[str, 'VPPCtl.RuntimeThreadStat'] = field(default_factory=dict)

    _RUNTIME_THREAD_TITLE_PATTERN = re.compile(r'^Thread \d+ (.+) \(lcore \d+\)$')
    _RUNTIME_THREAD_VECTOR_RATES_PATTERN = re.compile(r'^vector rates in (.+), out (.+), drop (.+), punt (.+)$')

    def show_runtime(self, include_threads: Optional[Iterable[str]] = None, **kwargs: Any) -> RuntimeStat:
        """
        Call `vppctl show runtime` and return the parsed output.

        :param include_threads: Threads to include in the output; if `None`, include all threads

        :returns: Parsed output
        """
        output = self._invoke(['show', 'runtime'], **kwargs).stdout.decode()
        threads_data = {}
        sections = list(map(str.strip, output.split('---------------')))
        for section in sections:
            line_iterator = iter(section.strip().split('\n'))
            thread = self._RUNTIME_THREAD_TITLE_PATTERN.fullmatch(next(line_iterator).strip()).group(1)  # type: ignore
            if include_threads is not None and thread not in include_threads:
                continue
            next(line_iterator)  # skip 'Time 168135.7, 10 sec internal node vector rate 0.00 loops/sec 159186.44'
            vector_rates_data = []
            for value in self._RUNTIME_THREAD_VECTOR_RATES_PATTERN.fullmatch(next(line_iterator).strip()).groups():  # type: ignore
                vector_rates_data.append(float(value))
            vector_rates_data = self.RuntimeVectorRateStat(*vector_rates_data)
            next(line_iterator)  # skip headers (we assume the order of stats is consistent with fields in RuntimeStat, as it is difficult to parse headers)
            nodes_data = {}
            for line in line_iterator:
                node, state, *values = line.split()
                for _ in range(len(values) - len(fields(self.RuntimeNodeStat)) + 1):  # 'state' can be a multi-word string
                    state += ' ' + values.pop(0)
                nodes_data[node] = self.RuntimeNodeStat(state, *map(lambda s: float(s), values))
            threads_data[thread] = self.RuntimeThreadStat(vector_rates=vector_rates_data, nodes=nodes_data)
        return self.RuntimeStat(threads=threads_data)

    @dataclass
    class MonitorDirectionStat:
        pps: int
        bps: int

    @dataclass
    class MonitorInterfaceStat:
        rx: 'VPPCtl.MonitorDirectionStat' = field(default_factory=lambda: VPPCtl.MonitorDirectionStat(0, 0))
        tx: 'VPPCtl.MonitorDirectionStat' = field(default_factory=lambda: VPPCtl.MonitorDirectionStat(0, 0))

    @dataclass
    class MonitorStat:
        interfaces: Dict[str, 'VPPCtl.MonitorInterfaceStat'] = field(default_factory=dict)

    def monitor_interface(self, interface: str, interval: Optional[int] = None, **kwargs: Any) -> MonitorStat:
        """
        Call `vppctl monitor interface <interface> interval <interval> count 1`.

        :param interface: Interface name
        :param interval: Interval in seconds

        :returns: Parsed output
        """
        args = ['monitor', 'interface', interface]
        if interval is not None:
            args += ['interval', str(interval)]
        # TODO: Add support for count
        args += ['count', '1']
        output = self._invoke(args, **kwargs).stdout.decode()
        return self._parse_monitor_stat(interface, output)

    _MONITOR_STAT_LINE_PATTERN = re.compile(r'^rx: (.+)pps (.+)bps tx: (.+)pps (.+)bps$')
    _MONITOR_STAT_UNITS = {'k': 1_000, 'm': 1_000_000, 'g': 1_000_000_000}

    @classmethod
    def _parse_monitor_stat(cls, interface: str, output: str) -> MonitorStat:
        line, *_ = output.strip().split('\n')
        # TODO: Add support for multiple lines
        match = cls._MONITOR_STAT_LINE_PATTERN.fullmatch(line.strip())
        if not match:
            raise ValueError('No match found; this should not happen')
        components = list(match.groups())
        for i, component in enumerate(components):
            if component[-1].lower() in cls._MONITOR_STAT_UNITS:
                factor = cls._MONITOR_STAT_UNITS[component[-1].lower()]
                component = component[:-1]
            else:
                factor = 1
            components[i] = int(float(component) * factor)
        rx_pps, rx_bps, tx_pps, tx_bps = cast(List[int], components)
        return cls.MonitorStat(
            interfaces={
                interface: cls.MonitorInterfaceStat(
                    rx=cls.MonitorDirectionStat(rx_pps, rx_bps),
                    tx=cls.MonitorDirectionStat(tx_pps, tx_bps),
                )
            }
        )


def generate_dpdk_batch_configs(interface: str, sizes: Iterable[int], timeouts: Iterable[float]) -> Iterable[VPPCtl.DPDKBatchConfig]:
    """
    Generate DPDK batching configurations.

    :param interface: Interface name
    :param sizes: Batch sizes
    :param timeouts: Timeouts (in seconds)

    :returns: Iterable of configurations
    """
    for size in sizes:
        for timeout in timeouts:
            interfaces_data = {interface: VPPCtl.DPDKInterfaceBatchConfig(size, timeout)}
            yield VPPCtl.DPDKBatchConfig(interfaces=interfaces_data)


def generate_batch_configs(nodes: List[str], sizes: Iterable[int], timeouts: Iterable[int]) -> Iterable[VPPCtl.BatchConfig]:
    """
    Generate node batching configurations.

    :param nodes: Node names
    :param sizes: Batch sizes
    :param timeouts: Timeouts (in us)

    :returns: Iterable of configurations
    """
    for size in sizes:
        for timeout in timeouts:
            nodes_data: Dict[Union[str, int], VPPCtl.NodeBatchConfig] = {node: VPPCtl.NodeBatchConfig(size, timeout) for node in nodes}
            yield VPPCtl.BatchConfig(nodes=nodes_data)


def generate_batch_config_combinations(
    nodes: List[str],
    sizes: Iterable[int],
    timeouts: Iterable[int],
    partial: Optional[Dict[Union[int, str], VPPCtl.NodeBatchConfig]] = None,
) -> Iterable[VPPCtl.BatchConfig]:
    """
    Generate all possible combinations of node batching configurations.

    :param nodes: Node names
    :param sizes: Batch sizes
    :param timeouts: Timeouts (in us)

    :returns: Iterable of configurations
    """
    if partial is None:
        partial = {}
    if len(partial) == len(nodes):
        yield VPPCtl.BatchConfig(nodes=partial)
    else:
        for size in sizes:
            for timeout in timeouts:
                new_partial = {**partial, nodes[len(partial)]: VPPCtl.NodeBatchConfig(size, timeout)}
                yield from generate_batch_config_combinations(nodes, sizes, timeouts, new_partial)


class Perf(CommandLineTool):
    DEFAULT_COMMAND = ('perf',)

    def __init__(self, command: Iterable[str] = DEFAULT_COMMAND, verbose: bool = False) -> None:
        super().__init__(command, verbose)

    _STAT_PATTERN = re.compile(r"Performance counter stats for process id '(\d+)':\s*\n*((?:.*\n)*).*seconds time elapsed")

    @dataclass
    class CacheData:
        """
        Output of `perf stat` for cache statistics.
        """

        l1_dcache_loads: int
        l1_dcache_load_misses: int
        l1_dcache_store: int
        icache_hit: int
        icache_misses: int
        icache_ifdata_stall: int
        llc_loads: int
        llc_load_misses: int
        llc_stores: int
        l2_rqsts_all_demand_miss: int

    # TODO: Revisit this design; generalize metrics
    def stat_cache(
        self,
        command: Iterable[str],
        pids: Optional[Iterable[int]] = None,
        parse_func: Optional[Callable[[str], Any]] = None,
        **kwargs: Any,
    ) -> CacheData:
        """
        Call `perf stat` and return the parsed output.

        :param command: Command to run
        :param pids: PIDs to measure; if `None`, measure all processes
        :param parse_func: Function to parse the output (for processing output of the command being run)
        :param kwargs: Keyword arguments to pass to `invoke`

        :returns: Parsed output
        """
        args = ['stat']
        args += ['-e', 'L1-dcache-loads,L1-dcache-load-misses,L1-dcache-store,icache.hit,icache.misses,icache.ifdata_stall,LLC-loads,LLC-load-misses,LLC-stores,L2_RQSTS.ALL_DEMAND_MISS']
        if pids is not None:
            args += ['-p', ','.join(str(pid) for pid in pids)]
        args += command
        process = self._invoke(args, **kwargs)
        output = process.stderr.decode()
        if parse_func:
            # TODO: Support stderr
            command_output = process.stdout.decode()
            parse_func(command_output)
        output = self._remove_control_chars(output)
        match = self._STAT_PATTERN.search(output)
        if not match:
            raise RuntimeError('No match found; this should not happen\nstderr:\n' + output)
        perf_section = match.group(2)
        lines = perf_section.strip().split('\n')
        data = {}
        for line in lines:
            value, name, *_ = line.split()
            name = self._normalize_identifier(name)
            value = int(value.replace(',', ''))
            data[name] = value
        return self.CacheData(**data)

    def stat_cache_with_duration(self, duration: Union[int, str], pids: Optional[Iterable[int]] = None, **kwargs: Any) -> CacheData:
        """
        Call `perf stat` and return the parsed output.

        :param duration: Duration of the measurement
        :param pids: PIDs to measure; if `None`, measure all processes

        :returns: Parsed output
        """
        return self.stat_cache(['sleep', str(duration)], pids=pids, **kwargs)


def _as_serializable(data: Any):
    return dataclasses._asdict_inner(data, dict_factory=dict)  # type: ignore


class _ExperimentRecorder:
    def __init__(self, verbose: bool = False) -> None:
        self._verbose = verbose


class SQLAlchemyExperimentRecorder(_ExperimentRecorder):
    """
    Experiment recorder using SQLAlchemy for use with `run_experiment`.
    """

    def __init__(
        self,
        url_template: str = 'sqlite:///experiments.sqlite',
        table_template: str = 'experiments',
        verbose: bool = False,
    ) -> None:
        super().__init__(verbose)
        self._url_template = url_template
        self._table_template = table_template
        self._experiment_id = None
        self._engine = None
        self._table = None

    def __call__(self, experiment_id: str, setting: Any, stat: Any):
        if self._experiment_id is None:
            self._experiment_id = experiment_id
        elif self._experiment_id != experiment_id:
            raise ValueError('experiment_id must be the same for all calls')
        data = {
            'experiment_id': experiment_id,
            'setting': setting,
            'stat': stat,
        }
        data = self._flatten_dict(_as_serializable(data))
        if self._engine is None:
            if self._verbose:
                print('Initializing engine and table', file=sys.stderr)
            self._initialize_engine_and_table(experiment_id, data)
        new_keys = set(data.keys()) - set(self._table.columns.keys())  # type: ignore
        if new_keys:
            if self._verbose:
                print(f'Adding columns as new keys appear in the data: {new_keys}', file=sys.stderr)
            self._add_columns({key: data[key] for key in new_keys})
        with self._engine.connect() as conn:  # type: ignore
            statement = insert(self._table).values(**data)
            conn.execute(statement)
            conn.commit()

    def _initialize_engine_and_table(self, experiment_id: str, data: dict):
        if self._engine is not None:
            raise RuntimeError('Engine is already initialized')
        self._engine = create_engine(self._url_template.format(experiment_id=experiment_id), future=True)
        columns = [
            Column('id', Integer, Identity(), primary_key=True),
            Column('create_time', DateTime, server_default=func.now()),
            Column('deleted', Boolean, server_default=text('0')),  # not used for now
        ]
        for key, value in data.items():
            columns.append(Column(key, self._determine_column_type(value)))
        self._table = Table(self._table_template.format(experiment_id=experiment_id), MetaData(), *columns)
        self._table.create(self._engine)  # type: ignore

    def _add_columns(self, new_data: dict):
        columns = []
        for key, value in new_data.items():
            columns.append(Column(key, self._determine_column_type(value)))
        with self._engine.connect() as conn:  # type: ignore
            for column in columns:
                statement = DDL(
                    'ALTER TABLE `%(table)s` ADD COLUMN %(column)s',
                    context={
                        'table': self._table.name,  # type: ignore
                        'column': CreateColumn(column).compile(conn),  # type: ignore
                    },
                )
                conn.execute(statement)  # type: ignore
            conn.commit()
        for column in columns:
            self._table.append_column(column)  # type: ignore

    @classmethod
    def _flatten_dict(cls, d: dict, parent_key: str = '') -> dict:
        items = []
        for k, v in d.items():
            new_key = f'{parent_key}.{k}' if parent_key else k
            if isinstance(v, dict):
                items.extend(cls._flatten_dict(v, new_key).items())
            else:
                items.append((new_key, v))
        return dict(items)

    @classmethod
    def _determine_column_type(cls, value: Any) -> type:
        if isinstance(value, int):
            return Integer
        if isinstance(value, float):
            return Float
        return String


class JSONLExperimentRecorder(_ExperimentRecorder):
    """
    Experiment recorder using JSONL for use with `run_experiment`.
    """

    def __init__(self, path_template: str = 'experiments.jsonl', verbose: bool = False) -> None:
        super().__init__(verbose)
        self._path_template = path_template

    def __call__(self, experiment_id: str, setting: Any, stat: Any):
        path = self._path_template.format(experiment_id=experiment_id)
        data = _as_serializable(dict(experiment_id=experiment_id, setting=setting, stat=stat))
        with open(path, 'a') as f:
            f.write(json.dumps(data, indent=None) + '\n')


def run_experiment(
    settings: Iterable[Any],
    *,
    apply_func: Callable[[Any], Any],
    stat_func: Callable[[], Any],
    record_func: Callable[[str, Any, Any], Any] = lambda x, y, z: None,
    id_: Optional[str] = None,
    duration: float = 0.0,
    repeat_count: int = 1,
    repeat_interval: float = 0.0,
):
    """
    Iterate over the settings and run the experiment.

    :param settings: Settings to iterate over
    :param apply_func: Function to apply the setting
    :param stat_func: Function to get statistics
    :param record_func: Function to record the data
    :param id_: Experiment ID (default: current time)
    :param duration: Duration of each experiment
    :param repeat_count: Number of times to repeat the experiment
    :param repeat_interval: Interval between each experiment
    """
    if not id_:
        id_ = str(datetime.strftime(datetime.now(), '%Y%m%d%H%M%S'))
    for setting in settings:
        print(f'{id_}: setting: {setting}')
        for i in range(repeat_count):
            if repeat_interval > 0:
                time.sleep(repeat_interval)
            print(f'{id_}: running experiment {i + 1}/{repeat_count}')
            apply_func(setting)
            if duration > 0:
                time.sleep(duration)
            stat = stat_func()
            record_func(id_, setting, stat)


def _reset_all_stats():
    vppctl.perfmon_stop()
    vppctl.perfmon_reset()
    vppctl.clear_runtime()
    vppctl.dpdk_latency_reset()
    # TODO: Revisit this
    # vppctl.perfmon_start('cache-detail')


def _find_process(include_comm: Iterable[str], raise_on_not_found: bool = True) -> List[int]:
    output = CommandLineTool(['ps', '-eLo', 'pid,comm']).invoke().stdout.decode()
    line_iterator = iter(output.strip().split('\n'))
    next(line_iterator)  # skip header
    pids = []
    for line in line_iterator:
        pid, comm = line.split(maxsplit=1)
        if comm in include_comm:
            pids.append(int(pid))
    if not pids and raise_on_not_found:
        raise RuntimeError(f'Cannot find process with the given comm: {include_comm}')
    return pids


def _merge_dict(dest: Dict[Any, Any], src: Dict[Any, Any]) -> Dict[Any, Any]:
    for key, value in src.items():
        if key in dest and isinstance(dest[key], dict) and isinstance(value, dict):
            dest[key] = _merge_dict(dest[key], value)
        else:
            dest[key] = value
    return dest


BATCH_NODES_IP4 = ['ip4-lookup', 'nat-pre-in2out', 'ip4-inacl']
BATCH_NODES_IP6 = ['ip6-input']
BATCH_NODES_ETH1 = ['Ethernet1-output']
# BATCH_NODES = [*BATCH_NODES_IP4, *BATCH_NODES_IP6, *BATCH_NODES_ETH1]
BATCH_NODES = ['nat44-ed-in2out', 'nat44-ed-in2out-slowpath', 'Ethernet1-output']
# BATCH_SIZES = [32, 48, 64, 128, 256]
BATCH_SIZES = [32, 48, 64, 128]
BATCH_TIMEOUTS = [100]

DPDK_RX_INTERFACE = 'Ethernet0'
DPDK_TX_INTERFACE = 'Ethernet1'
DPDK_BATCH_SIZES = BATCH_SIZES.copy()
DPDK_BATCH_TIMEOUTS = [t / 1_000_000 for t in BATCH_TIMEOUTS]

DURATION = 10
REPEAT_COUNT = 1
REPEAT_INTERVAL = 0
THREADS = ['vpp_wk_0']

RECORD_URL_TEMPLATE = 'sqlite:///vpp_exp_{experiment_id}.sqlite'
RECORD_TABLE_TEMPLATE = 'vpp_exp_data'

VERBOSE = True

vppctl = VPPCtl(['sudo', 'vppctl', '-s', '/run/vpp/remote/cli_remote.sock'], verbose=VERBOSE)
perf = Perf(['sudo', 'perf'], verbose=VERBOSE)


def main():
    # Options for 'settings'
    node_batch_configs = generate_batch_configs(BATCH_NODES, BATCH_SIZES, BATCH_TIMEOUTS)
    node_batch_combinations = generate_batch_config_combinations(BATCH_NODES, BATCH_SIZES, BATCH_TIMEOUTS)
    dpdk_batch_configs = generate_dpdk_batch_configs(DPDK_RX_INTERFACE, DPDK_BATCH_SIZES, DPDK_BATCH_TIMEOUTS)
    node_and_dpdk_batch_configs = map(
        lambda x: _merge_dict(x[0], x[1]),
        map(
            _as_serializable,
            zip(
                generate_batch_configs(BATCH_NODES, BATCH_SIZES, BATCH_TIMEOUTS),
                generate_dpdk_batch_configs(DPDK_RX_INTERFACE, DPDK_BATCH_SIZES, DPDK_BATCH_TIMEOUTS),
            ),
        ),
    )
    node_and_dpdk_batch_combinations = map(
        lambda x: _merge_dict(x[0], x[1]),
        map(
            _as_serializable,
            product(
                generate_batch_config_combinations(BATCH_NODES, BATCH_SIZES, BATCH_TIMEOUTS),
                generate_dpdk_batch_configs(DPDK_RX_INTERFACE, DPDK_BATCH_SIZES, DPDK_BATCH_TIMEOUTS),
            ),
        ),
    )
    node_and_dpdk_grouped_batch_combinations = map(
        lambda x: reduce(lambda a, b: _merge_dict(a, b), x, {}),
        map(
            _as_serializable,
            product(
                generate_batch_configs(BATCH_NODES_IP4, BATCH_SIZES, BATCH_TIMEOUTS),
                generate_batch_configs(BATCH_NODES_IP6, BATCH_SIZES, BATCH_TIMEOUTS),
                generate_batch_configs(BATCH_NODES_ETH1, BATCH_SIZES, BATCH_TIMEOUTS),
                generate_dpdk_batch_configs(DPDK_RX_INTERFACE, DPDK_BATCH_SIZES, DPDK_BATCH_TIMEOUTS),
            ),
        ),
    )

    # Options for 'apply_func'
    def apply_vpp_node_batch(setting):
        vppctl.set_node_batch(setting)
        _reset_all_stats()

    def apply_dpdk_batch(setting):
        vppctl.set_dpdk_batchsize(setting)
        _reset_all_stats()

    def apply_vpp_and_dpdk_batch(setting):
        vppctl.set_node_batch(setting['nodes'])
        vppctl.set_dpdk_batchsize(setting['interfaces'])
        _reset_all_stats()

    # Options for 'stat_func'
    def stat_vpp_nodes():
        res = {}
        for data in (
            vppctl.show_perfmon_statistics(include_threads=THREADS),
            vppctl.show_dpdk_latency(),
            vppctl.show_runtime(include_threads=THREADS),
        ):
            res = _merge_dict(res, _as_serializable(data))
        return res

    def stat_total():
        return perf.stat_cache_with_duration(DURATION, _find_process(THREADS))

    def stat_total_with_monitor():
        command = [*vppctl.command, 'monitor', 'interface', DPDK_TX_INTERFACE, 'interval', str(DURATION), 'count', '1']
        throughputs_data = []
        cache_data = perf.stat_cache(
            command,
            _find_process(THREADS),
            parse_func=lambda output: throughputs_data.append(VPPCtl._parse_monitor_stat(DPDK_TX_INTERFACE, output)),  # FIXME:
        )
        res = {}
        for data in (throughputs_data[0], cache_data):
            res = _merge_dict(res, _as_serializable(data))
        return res

    # Options for 'record_func'
    record_database = SQLAlchemyExperimentRecorder(RECORD_URL_TEMPLATE, RECORD_TABLE_TEMPLATE, verbose=VERBOSE)
    record_jsonl = JSONLExperimentRecorder(verbose=VERBOSE)

    parser = argparse.ArgumentParser()
    parser.add_argument('--settings', type=locals().__getitem__, default=node_batch_configs)
    parser.add_argument('--apply-func', type=locals().__getitem__, default=apply_vpp_node_batch)
    parser.add_argument('--stat-func', type=locals().__getitem__, default=stat_vpp_nodes)
    parser.add_argument('--record-func', type=locals().__getitem__, default=record_database)
    parser.add_argument('--duration', type=float, default=DURATION)
    parser.add_argument('--repeat-count', type=int, default=REPEAT_COUNT)
    parser.add_argument('--repeat-interval', type=float, default=REPEAT_INTERVAL)
    kwargs = vars(parser.parse_args())

    run_experiment(**kwargs)


if __name__ == '__main__':
    sys.exit(main())
