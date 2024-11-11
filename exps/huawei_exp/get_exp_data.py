import dataclasses
import json
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple, Union

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
            return subprocess.run(command, **kwargs)
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
    class DPDKBatchConfig:
        size: int
        """Batch size of `dpdk-input`."""
        timeout: float
        """Timeout (in seconds) of `dpdk-input`."""

    def set_dpdk_batchsize(
        self,
        config: Mapping[str, Union[DPDKBatchConfig, Mapping[str, Any]]],
        **kwargs: Any,
    ) -> None:
        """
        Set `dpdk-input` batching configuration with `vppctl set dpdk batchsize`.

        :param config: Configuration or mapping from interface name to the configuration
        """
        if len(config) != 1:
            raise ValueError('config must have exactly one element')
        interface, batch_config = next(iter(config.items()))
        if not isinstance(batch_config, self.DPDKBatchConfig):
            batch_config = self.DPDKBatchConfig(**batch_config)
        self._invoke(
            ['set', 'dpdk', 'batchsize', interface, str(batch_config.size), 'timeout', str(batch_config.timeout)],
            **kwargs,
        )

    @dataclass
    class BatchConfig:
        size: Optional[int] = field(default=None)
        """Batch size of the node; set to `None` to not change"""
        timeout: Optional[int] = field(default=None)
        """Timeout (in us) of the node; set to `None` to not change"""

    def set_node_batch(
        self,
        config: Mapping[Union[int, str], Union[BatchConfig, Mapping[str, Any]]],
        **kwargs: Any,
    ) -> None:
        """
        Set node batching configurations with `vppctl set node batch`.

        :param config: Mapping of node index or name to the configuration
        """
        args = ['set', 'node', 'batch']
        for k, c in config.items():
            if isinstance(k, int):
                args += ['index', str(k)]
            else:
                args += [str(k)]
            if not isinstance(c, self.BatchConfig):
                c = self.BatchConfig(**c)
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

    def show_dpdk_latency(self, **kwargs: Any) -> Dict[str, DPDKInterfaceStat]:
        """
        Call `vppctl show dpdk latency` and return the parsed output.

        :returns: Parsed output (mapping from interface to statistics)
        """
        res = {}
        output = self._invoke(['show', 'dpdk', 'latency'], **kwargs).stdout.decode()
        line_iterator = iter(output.strip().split('\n'))
        next(line_iterator)  # skip 'current time_diff(s): 1619'
        for line in line_iterator:
            interface, *stat_parts = line.split(',')
            stat_data = {self._normalize_identifier(name): int(value) for name, value in map(lambda s: s.split(':'), stat_parts)}
            protocol = stat_data.pop('protocol_identifier', None)
            if protocol is None:
                res[interface] = self.DPDKInterfaceStat(**stat_data)  # type: ignore
            else:
                # Interface-level stats always come before protocol-level stats, so this is safe
                res[interface].protocols[protocol] = self.DPDKProtocolStat(**stat_data)
        return res

    @dataclass
    class PerfmonStat:
        """
        Output of `vppctl show perfmon statistics` for each node.
        """

        l1i_miss_per_pkt: float
        l1d_miss_per_pkt: float
        l2_miss_per_pkt: float
        l3_miss_per_pkt: float

    def show_perfmon_statistics(self, include_threads: Optional[Iterable[str]] = None, **kwargs: Any) -> Dict[str, Dict[str, PerfmonStat]]:
        """
        Call `vppctl show perfmon statistics` and return the parsed output.

        :param include_threads: Threads to include in the output; if `None`, include all threads

        :returns: Parsed output (mapping from thread to node to statistics header to value)
        """
        res = {}
        output = self._invoke(['show', 'perfmon', 'statistics'], **kwargs).stdout.decode()
        output = self._remove_control_chars(output)
        line_iterator = iter(output.strip().split('\n'))
        next(line_iterator)  # skip title
        next(line_iterator)  # skip header (we assume the order of stats is consistent with fields in PerfmonStat, as it is difficult to parse headers)
        thread = None
        data = {}
        for line in line_iterator:
            if '(' in line:  # e.g. 'vpp_wk_0 (1)'
                if thread is not None and (include_threads is None or thread in include_threads):
                    res[thread] = data
                thread = line.split()[0]
                data = {}
            else:
                node, *values = line.split()
                data[node] = self.PerfmonStat(*map(float, values))
        if thread is not None and (include_threads is None or thread in include_threads):
            res[thread] = data
        return res

    @dataclass
    class RuntimeStat:
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

    _RUNTIME_THREAD_TITLE_PATTERN = re.compile(r'^Thread \d+ (.+) \(lcore \d+\)$')

    def show_runtime(self, include_threads: Optional[Iterable[str]] = None, **kwargs: Any) -> Dict[str, Dict[str, RuntimeStat]]:
        """
        Call `vppctl show runtime` and return the parsed output.

        :param include_threads: Threads to include in the output; if `None`, include all threads

        :returns: Parsed output (mapping from thread to node to statistics)
        """
        res = {}
        output = self._invoke(['show', 'runtime'], **kwargs).stdout.decode()
        sections = list(map(str.strip, output.split('---------------')))
        for section in sections:
            line_iterator = iter(section.strip().split('\n'))
            thread = self._RUNTIME_THREAD_TITLE_PATTERN.fullmatch(next(line_iterator).strip()).group(1)  # type: ignore
            if include_threads is not None and thread not in include_threads:
                continue
            next(line_iterator)  # skip 'Time 168135.7, 10 sec internal node vector rate 0.00 loops/sec 159186.44'
            next(line_iterator)  # skip 'vector rates in 0.0000e0, out 0.0000e0, drop 0.0000e0, punt 0.0000e0'
            next(line_iterator)  # skip headers (we assume the order of stats is consistent with fields in RuntimeStat, as it is difficult to parse headers)
            data = {}
            for line in line_iterator:
                node, state, *values = line.split()
                for _ in range(len(values) - len(fields(self.RuntimeStat)) + 1):  # 'state' can be a multi-word string
                    state += ' ' + values.pop(0)
                data[node] = self.RuntimeStat(state, *map(lambda s: float(s), values))
            res[thread] = data
        return res


def generate_dpdk_batch_configs(interface: str, sizes: Iterable[int], timeouts: Iterable[float]) -> Iterable[Dict[str, VPPCtl.DPDKBatchConfig]]:
    """
    Generate DPDK batching configurations.

    :param interface: Interface name
    :param sizes: Batch sizes
    :param timeouts: Timeouts (in seconds)

    :returns: Iterable of configurations
    """
    for size in sizes:
        for timeout in timeouts:
            yield {interface: VPPCtl.DPDKBatchConfig(size, timeout)}


def generate_batch_configs(nodes: List[str], sizes: Iterable[int], timeouts: Iterable[int]) -> Iterable[Dict[str, VPPCtl.BatchConfig]]:
    """
    Generate node batching configurations.

    :param nodes: Node names
    :param sizes: Batch sizes
    :param timeouts: Timeouts (in us)

    :returns: Iterable of configurations
    """
    for size in sizes:
        for timeout in timeouts:
            yield {node: VPPCtl.BatchConfig(size, timeout) for node in nodes}


def generate_batch_config_combinations(
    nodes: List[str], sizes: Iterable[int], timeouts: Iterable[int], partial: Optional[Dict[str, VPPCtl.BatchConfig]] = None
) -> Iterable[Dict[str, VPPCtl.BatchConfig]]:
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
        yield partial
    else:
        for size in sizes:
            for timeout in timeouts:
                new_partial = {**partial, nodes[len(partial)]: VPPCtl.BatchConfig(size, timeout)}
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

    # TODO: Generalize this
    def stat_cache(self, duration: Union[int, str], pids: Optional[Iterable[int]], **kwargs: Any) -> CacheData:
        """
        Call `perf stat` and return the parsed output.

        :param duration: Duration of the measurement
        :param pids: PIDs to measure; if `None`, measure all processes

        :returns: Parsed output
        """
        args = ['stat']
        args += ['-e', 'L1-dcache-loads,L1-dcache-load-misses,L1-dcache-store,icache.hit,icache.misses,icache.ifdata_stall,LLC-loads,LLC-load-misses,LLC-stores,L2_RQSTS.ALL_DEMAND_MISS']
        if pids is not None:
            args += ['-p', ','.join(str(pid) for pid in pids)]
        args += ['sleep', str(duration)]
        output = self._invoke(args, **kwargs).stderr.decode()
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


class _ExperimentRecorder:
    def __init__(self, verbose: bool = False) -> None:
        self._verbose = verbose

    @classmethod
    def _as_serializable(cls, data: Any):
        return dataclasses._asdict_inner(data, dict_factory=dict)  # type: ignore


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
        data = self._flatten_dict(self._as_serializable(data))
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
        data = self._as_serializable(dict(experiment_id=experiment_id, setting=setting, stat=stat))
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
    vppctl.perfmon_start('cache-detail')


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


BATCH_NODES = ['ip4-lookup', 'ip6-input', 'nat-pre-in2out', 'ip4-inacl']
BATCH_SIZES = [32, 64, 96, 128, 160, 192, 224, 256]
BATCH_TIMEOUTS = [100]

DPDK_RX_INTERFACE = 'Ethernet0'
DPDK_BATCH_SIZES = BATCH_SIZES.copy()
DPDK_BATCH_TIMEOUTS = BATCH_TIMEOUTS.copy()

DURATION = 10
REPEAT_COUNT = 5
THREADS = ['vpp_wk_0']

RECORD_URL_TEMPLATE = 'sqlite:///vpp_exp_{experiment_id}.sqlite'
RECORD_TABLE_TEMPLATE = 'vpp_exp_data'

VERBOSE = True

vppctl = VPPCtl(['sudo', 'vppctl', '-s', '/run/vpp/remote/cli_remote.sock'], verbose=VERBOSE)
perf = Perf(['sudo', 'perf'], verbose=VERBOSE)


if __name__ == '__main__':
    node_batch_combinations = generate_batch_config_combinations(BATCH_NODES, BATCH_SIZES, BATCH_TIMEOUTS)
    node_batch_configs = generate_batch_configs(BATCH_NODES, BATCH_SIZES, BATCH_TIMEOUTS)
    dpdk_batch_configs = generate_dpdk_batch_configs(DPDK_RX_INTERFACE, DPDK_BATCH_SIZES, DPDK_BATCH_TIMEOUTS)

    def apply_vpp_node_batch(setting):
        vppctl.set_node_batch(setting)
        _reset_all_stats()

    def apply_dpdk_batch(setting):
        vppctl.set_dpdk_batchsize(setting)
        _reset_all_stats()

    def stat_vpp_nodes():
        res = {}
        res.update(vppctl.show_perfmon_statistics(include_threads=THREADS))
        res.update(vppctl.show_dpdk_latency())
        res.update(vppctl.show_runtime(include_threads=THREADS))
        return res

    def stat_total():
        return perf.stat_cache(DURATION, _find_process(THREADS))

    record_database = SQLAlchemyExperimentRecorder(RECORD_URL_TEMPLATE, RECORD_TABLE_TEMPLATE, verbose=VERBOSE)
    record_jsonl = JSONLExperimentRecorder(verbose=VERBOSE)

    run_experiment(
        node_batch_combinations,
        apply_func=apply_vpp_node_batch,
        stat_func=stat_vpp_nodes,
        # stat_func=stat_total,
        record_func=record_database,
        # record_func=record_jsonl,
        duration=DURATION,
        repeat_count=REPEAT_COUNT,
    )
