

from configs import cfg
from src.utils.record_log import _logger
import tensorflow as tf

from src.model.model_template import ModelTemplate
from src.nn_utils.nn import linear
from src.nn_utils.integration_func import generate_embedding_mat
from src.nn_utils.baselines.interface import sentence_encoding_models


class ModelContextFusion(ModelTemplate):
    def __init__(self, token_emb_mat, glove_emb_mat, tds, cds, tl, scope):
        super(ModelContextFusion, self).__init__(token_emb_mat, glove_emb_mat, tds, cds, tl, scope)
        self.update_tensor_add_ema_and_opt()

    def build_network(self):
        _logger.add()
        _logger.add('building %s neural network structure...' % cfg.network_type)
        tds, cds = self.tds, self.cds
        tl = self.tl
        tel, cel, cos, ocd, fh = self.tel, self.cel, self.cos, self.ocd, self.fh
        hn = self.hn
        bs, sl1, sl2 = self.bs, self.sl1, self.sl2

        with tf.variable_scope('emb'):
            token_emb_mat = generate_embedding_mat(tds, tel, init_mat=self.token_emb_mat,
                                                   extra_mat=self.glove_emb_mat, extra_trainable=self.finetune_emb,
                                                   scope='gene_token_emb_mat')
            s1_emb = tf.nn.embedding_lookup(token_emb_mat, self.sent1_token)  # bs,sl1,tel
            s2_emb = tf.nn.embedding_lookup(token_emb_mat, self.sent2_token)  # bs,sl2,tel
            self.tensor_dict['s1_emb'] = s1_emb
            self.tensor_dict['s2_emb'] = s2_emb

        with tf.variable_scope('sent_encoding'):
            act_func_str = 'elu' if cfg.context_fusion_method in ['block', 'disa'] else 'relu'

            s1_rep = sentence_encoding_models(
                s1_emb, self.sent1_token_mask, cfg.context_fusion_method, act_func_str,
                'ct_based_sent2vec', cfg.wd, self.is_train, cfg.dropout, block_len=cfg.block_len)

            tf.get_variable_scope().reuse_variables()

            s2_rep = sentence_encoding_models(
                s2_emb, self.sent2_token_mask, cfg.context_fusion_method, act_func_str,
                'ct_based_sent2vec', cfg.wd, self.is_train, cfg.dropout, block_len=cfg.block_len)

            self.tensor_dict['s1_rep'] = s1_rep
            self.tensor_dict['s2_rep'] = s2_rep

        with tf.variable_scope('output'):
            act_func = tf.nn.elu if cfg.context_fusion_method in ['block', 'disa'] else tf.nn.relu

            out_rep = tf.concat([s1_rep, s2_rep, s1_rep - s2_rep, s1_rep * s2_rep], -1)
            pre_output = act_func(linear([out_rep], hn, True, 0., scope= 'pre_output', squeeze=False,
                                            wd=cfg.wd, input_keep_prob=cfg.dropout,is_train=self.is_train))
            logits = linear([pre_output], self.output_class, True, 0., scope= 'logits', squeeze=False,
                            wd=cfg.wd, input_keep_prob=cfg.dropout,is_train=self.is_train)
            self.tensor_dict[logits] = logits
        return logits # logits

