import math
import os

import tensorflow as tf

from configs import cfg
from src.dataset import Dataset
# from src.trainer import Trainer
from src.evaluator import Evaluator
from src.graph_handler import GraphHandler
from src.perform_recorder import PerformRecoder
from src.utils.file import load_file, save_file
from src.utils.record_log import _logger
from squad_sim_log_analysis import do_analysis_squad_sim
# choose model
network_type = cfg.network_type

if network_type == 'exp_context_fusion':
    from src.model.model_context_fusion import ModelContextFusion as Model


def output_model_params():
    _logger.add()
    _logger.add('==>model_title: ' + cfg.model_name[1:])
    _logger.add()
    for key,value in cfg.args.__dict__.items():
        if key not in ['test','shuffle']:
            _logger.add('%s: %s' % (key, value))


def train():
    output_model_params()
    loadFile = True
    ifLoad, data = load_file(cfg.processed_path, 'processed data', 'pickle')
    if not ifLoad or not loadFile:
        train_data_obj = Dataset(cfg.train_dataset_path, data_type='train')
        dev_data_obj = Dataset(cfg.dev_dataset_path, data_type='dev', dicts=train_data_obj.dicts)
        save_file({'train_data': train_data_obj, 'dev_data': dev_data_obj}, cfg.processed_path)
    else:
        train_data_obj = data['train_data']
        dev_data_obj = data['dev_data']

    train_data_obj.filter_data()
    emb_mat_token, emb_mat_glove = train_data_obj.emb_mat_token, train_data_obj.emb_mat_glove

    # for block len
    if cfg.block_len is None and cfg.context_fusion_method == 'block':
        _logger.add()
        _logger.add('calculating block length for dataset')
        statistic = train_data_obj.get_statistic()
        expected_n = statistic['mean'] + statistic['std'] * math.sqrt(2. * math.log(1. * cfg.train_batch_size))
        dy_block_len = math.ceil(math.pow(2 * expected_n, 1.0 / 3)) + 1  # fixme: change length
        cfg.block_len = dy_block_len
        _logger.add('block length is %d' % dy_block_len)

    with tf.variable_scope(network_type) as scope:
        model = Model(
            emb_mat_token, emb_mat_glove, len(train_data_obj.dicts['token']),
            cfg.word_embedding_length, cfg.hidden_units_num, scope.name)

    graph_handler = GraphHandler(model)
    evaluator = Evaluator(model)
    perform_recoder = PerformRecoder(3)

    if cfg.gpu_mem is None:
        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=cfg.gpu_mem,
                                    allow_growth=True)
        graph_config = tf.ConfigProto(gpu_options=gpu_options, allow_soft_placement=True)

    else:
        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=cfg.gpu_mem)
        graph_config = tf.ConfigProto(gpu_options=gpu_options)
    sess = tf.Session(config=graph_config)

    graph_handler.initialize(sess)

    # begin training
    steps_per_epoch = int(math.ceil(1.0 * train_data_obj.sample_num / cfg.train_batch_size))
    num_steps = cfg.num_steps or steps_per_epoch * cfg.max_epoch

    global_step = 0
    for sample_batch, batch_num, data_round, idx_b in train_data_obj.generate_batch_sample_iter(num_steps):
        global_step = sess.run(model.global_step) + 1
        if_get_summary = global_step % (cfg.log_period or steps_per_epoch) == 0

        loss, summary, train_op = model.step(sess, sample_batch, get_summary=if_get_summary)
        if global_step % 100 == 0:
            _logger.add('data round: %d: %d/%d, global step:%d -- loss: %.4f' %
                        (data_round, idx_b, batch_num, global_step, loss))

        if if_get_summary:
            graph_handler.add_summary(summary, global_step)

        # period evaluation
        if (global_step > (cfg.num_steps - 20000) or cfg.model_dir_suffix == 'test') and \
                                global_step % (cfg.eval_period or steps_per_epoch) == 0:
            # ---- dev ----
            dev_loss, dev_accu = evaluator.get_evaluation(
                sess, dev_data_obj, global_step
            )
            _logger.add('==> for dev, loss: %.4f, accuracy: %.4f' %
                        (dev_loss, dev_accu))
            is_in_top, deleted_step = perform_recoder.update_top_list(global_step, dev_accu, sess)

        this_epoch_time, mean_epoch_time = cfg.time_counter.update_data_round(data_round)
        if this_epoch_time is not None and mean_epoch_time is not None:
            _logger.add('##> this epoch time: %f, mean epoch time: %f' % (this_epoch_time, mean_epoch_time))
    _logger.writeToFile()
    do_analysis_squad_sim(_logger.path)


def main(_):
    if cfg.mode == 'train':
        train()
    else:
        raise ValueError('do not have mode: %s' % cfg.mode)


if __name__ == '__main__':
    tf.app.run()