
#!/usr/bin/env python

# --------------------------------------------------------
# Fast R-CNN
# Copyright (c) 2015 Microsoft
# Licensed under The MIT License [see LICENSE for details]
# Written by Ross Girshick
# --------------------------------------------------------

"""Train a Fast R-CNN network on a region of interest database."""

import _init_paths
from fast_rcnn.config import cfg, cfg_from_file, cfg_from_list
from datasets.factory import get_imdb
import datasets
import argparse
import pprint
import numpy as np
import sys
import os
import time
import cPickle as pickle

#gpu_id = '1'
gpu_id = os.environ["SGE_GPU"]
print gpu_id
os.environ["CUDA_LAUNCH_BLOCKING"]='1'
os.environ["THEANO_FLAGS"] = "device=gpu%s,floatX=float32,profile=False" % gpu_id
print os.environ["THEANO_FLAGS"]
sys.path.insert(0, '/nfs/isicvlnas01/users/yue_wu/thirdparty/keras_1.1.2/keras/' )
import keras
print keras.__version__


import roi_data_layer.roidb as rdl_roidb
from keras_model import prepare_data
from keras.utils.np_utils import to_categorical
from keras.callbacks import CSVLogger
from keras_model.myModelCheckpoint import MyModelCheckpoint
from keras.models import load_model


def get_training_roidb(imdb):
    """Returns a roidb (Region of Interest database) for use in training."""
    if cfg.TRAIN.USE_FLIPPED:
        print 'Appending horizontally-flipped training examples...'
        imdb.append_flipped_images()
        print 'done'

    print 'Preparing training data...'
    rdl_roidb.prepare_roidb(imdb)
    print 'done'

    return imdb.roidb
'''
# fbratio = foreground / background
def background_filter(roidb, fbratio = 1.0):                                                       
    for ind in xrange(len(roidb)):
        img_rois = roidb[ind]
        target_label = img_rois['bbox_targets'][:,0] # vector, target labels for all rois
        fore_indices = np.where(target_label != 0)[0] # vector
        back_indices = np.where(target_label == 0)[0] # vector
        num_fore = len(fore_indices)
        filtered_num_back = int(num_fore/fbratio)
        np.random.shuffle(back_indices)
        filtered_back_indices = back_indices[0:filtered_num_back] # shuffle indices to take background sample from      # vector                       
        filtered_indices = np.concatenate((fore_indices[:,np.newaxis],filtered_back_indices[:,np.newaxis])) # array
        filtered_indices = filtered_indices[:,0] # vector 
        roidb[ind]['box_normalized'] = img_rois['box_normalized'][filtered_indices]
        roidb[ind]['bbox_targets'] = img_rois['bbox_targets'][filtered_indices]
             
    return roidb
'''

# fbratio = foreground / background
def background_filter(roidb,fbratio = 1.0):
    for ind in xrange(len(roidb)):
        img_rois = roidb[ind]
        target_label = img_rois['bbox_targets'][:,0] # vector, target labels for all rois
        max_overlaps = img_rois['max_overlaps']
        fore_indices = np.where(target_label != 0)[0] # vector
        back_indices = np.where((target_label == 0) &  (max_overlaps >= 0.1))[0] # vector
        num_fore = len(fore_indices)
        filtered_num_back = min (int(num_fore/fbratio), len(back_indices))
        np.random.shuffle(back_indices)
        filtered_back_indices = back_indices[0:filtered_num_back] # shuffle indices to take background sample from      # vector                       
        filtered_indices = np.concatenate((fore_indices[:,np.newaxis],filtered_back_indices[:,np.newaxis])) # array
        filtered_indices = filtered_indices[:,0] # vector 
        roidb[ind]['box_normalized'] = img_rois['box_normalized'][filtered_indices]
        roidb[ind]['bbox_targets'] = img_rois['bbox_targets'][filtered_indices]
             
    return roidb

def parse_args():
    """
    Parse input arguments
    """
    parser = argparse.ArgumentParser(description='Train a Fast R-CNN network')
    #parser.add_argument('--gpu', dest='gpu_id',
    #                    help='GPU device id to use [0]',
    #                    default=0, type=int)
    parser.add_argument('--weights', dest='pretrained_model',
                        help='initialize with pretrained model weights',
                        default=None, type=str)
    parser.add_argument('--cfg', dest='cfg_file',
                        help='optional config file',
                        default=None, type=str)
    parser.add_argument('--imdb', dest='imdb_name',
                        help='dataset to train on',
                        default='voc_2012_trainval', type=str)
    parser.add_argument('--set', dest='set_cfgs',
                        help='set config keys', default=None,
                        nargs=argparse.REMAINDER)
    parser.add_argument('--data',dest='data_dir',
                        help = 'data directory',
                        default=None,type=str)
    parser.add_argument('--proposal',dest='proposal_method',
                        help = 'either ss or yolo',
                        default=None,type=str)
    parser.add_argument('--targetnorm',dest='targetnorm',
                        help = 'whether use target normalization',
                        default='1',type=str)
    parser.add_argument('--mergedense',dest='merge_dense',
                        help = 'whether merge dense layer of two branches',
                        default='1',type=str)
    parser.add_argument('--numbboxout',dest='num_bbox_out',
                        help = 'number of outputs for bbox regression branch',
                        default='84',type=str)
    parser.add_argument('--pool',dest='pool_method',
                        help = 'pooling method in roi_pooling layer',
                        default='maxpool',type=str)
    parser.add_argument('--outdir',dest='out_dir',
                        help = 'directory path to save models',
                        default='output/weights/',type=str)
    
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    return args


def datagen( data_list, mode = 'training', nb_epoch = -1 ) :
    epoch = 0
    nb_samples = len( data_list )
    indices = range( nb_samples )
    while ( epoch < nb_epoch ) or ( nb_epoch < 0 ) :
        if ( mode == 'training' ) :
            np.random.shuffle( indices )
        for idx in indices :
            X =  np.expand_dims( data_list[idx]['image_data'], axis = 0)
            R = np.expand_dims(data_list[idx]['box_normalized'],axis = 0)
            P = data_list[idx]['bbox_targets'][:,0].astype(np.int32) # get label
            P = np.expand_dims(to_categorical(P,21).astype(np.float32),axis = 0)
            B = np.expand_dims(data_list[idx]['bbox_targets'],axis=0) # get label+ bbox_coordinates
   
            yield ( { 'batch_of_images' : X ,
                      'batch_of_rois'   : R },
                    { 'proba_output'  : P ,
                      'bbox_output' : B} )
        epoch += 1


if __name__ == '__main__':
    args = parse_args()

    print('Called with args:')
    print(args)

    if args.cfg_file is not None:
        cfg_from_file(args.cfg_file)
    if args.set_cfgs is not None:
        cfg_from_list(args.set_cfgs)
    if args.data_dir is not None:
        datasets.DATA_DIR = args.data_dir
    if args.merge_dense is not None:
        cfg.NET.IF_MERGEDENSE = args.merge_dense
    if args.num_bbox_out is not None:
        cfg.NET.BBOX_OUT_NUM = args.num_bbox_out
    if args.pool_method is not None:
        cfg.NET.POOL_METHOD = args.pool_method
    
    print('Using config:')
    pprint.pprint(cfg)

    imdb = get_imdb(args.imdb_name)
    if args.proposal_method == 'ss':
        imdb.roidb_handler = imdb.selective_search_roidb
        print 'Using selective search proposals'
    elif args.proposal_method == 'yolo':
        imdb.roidb_handler = imdb.yolo_roidb
        print 'Using YOLO proposals'
    else:
        print "ERROR: SPECIFY PROPOSAL METHOD, EITHER 'ss' OR 'yolo'"
        sys.exit (-1)

    print 'Loaded dataset `{:s}` for training'.format(imdb.name)
    roidb = get_training_roidb(imdb)

    print 'Computing bounding-box regression targets...'
    bbox_means, bbox_stds = rdl_roidb.add_bbox_regression_targets(roidb)
    if args.targetnorm == '1': # use target normalization
        num_images = len(roidb)
        num_classes = roidb[0]['gt_overlaps'].shape[1]
        for im_i in xrange(num_images):
            targets = roidb[im_i]['bbox_targets']
            for cls in xrange(1, num_classes):
                cls_inds = np.where(targets[:, 0] == cls)[0]
                roidb[im_i]['bbox_targets'][cls_inds, 1:] -= bbox_means[cls, :]
                roidb[im_i]['bbox_targets'][cls_inds, 1:] /= bbox_stds[cls, :]
        
        print 'Using target normalizaton'
    else:
        print 'Not using target normalization'
    bbox_means = bbox_means.ravel()
    bbox_stds = bbox_stds.ravel()
    
    print 'loading images ...'
    prepare_data.add_image_data(roidb)
    print 'Computing normalized roi boxes coordinates ...'
    prepare_data.add_normalized_bbox(roidb)
    
    # -----------------------------------split train-val set ----------------------------------

    # split the roidb into 9:1 for training and validation
    total_number = len(roidb)
    train_number = int( total_number * 0.9) # train:val = 9:1
    val_number = total_number -train_number
    print 'total_number: '+str(total_number)+' train_number: '+str(train_number)+' val_number: '+str(val_number)

    print 'background-filtering roidb'
    roidb[0:train_number] = background_filter(roidb[0:train_number])

    trn_data_list = roidb[0:train_number]  
    #trn = datagen( trn_data_list, nb_epoch = len(trn_data_list) )   
    # generate data infinitely
    trn = datagen( trn_data_list, nb_epoch = -1, mode = 'training' )   
    
    val_data_list = roidb[train_number:]
    val = datagen( val_data_list, nb_epoch = -1, mode = 'validation')

    # --------------------------------- define callbacks --------------------------------------
    #csv_logger = CSVLogger('output/2012_trainval.log')
    # save the model every epoch
    
    if not os.path.isdir(args.out_dir):
        os.mkdir(args.out_dir)

    prefix = args.imdb_name[4:]+'_'+args.proposal_method+'_targetnorm'+args.targetnorm+'_mergedense'+args.merge_dense+'_numbboxout'+args.num_bbox_out+'_'+args.pool_method+'_'
    model_save_path = args.out_dir +prefix+'samperepoch1000_bgfilter_lr0.0001-train-{epoch:02d}-{val_loss:.2f}.hdf5'

    if args.targetnorm == '1':
        # MyModelCheckpoint is save_weights_only = True
        check_point = MyModelCheckpoint(filepath = model_save_path, means = bbox_means, stds = bbox_stds , monitor = 'val_loss',save_best_only = False)
    else:
        # default: save_weights_only = True
        check_point = MyModelCheckpoint(filepath = model_save_path,  monitor = 'val_loss',save_best_only = False)



    # ----------------------------load model and weights(if any)---------------------------------
    from keras_model.fastrcnn import fast  # has to be called after setting correct cfg.NET values

    # if has pretrained model, load weights from hdf5 file
    if args.pretrained_model is not None:
        fast.load_weights(args.pretrained_model)
        print 'loaded pretrained weights from '+args.pretrained_model
    

    # =============================start training ---------------------------------------------
    print "training ..."
    tic  = time.clock()
    history = fast.fit_generator(trn,samples_per_epoch = 1000 ,nb_epoch = 1000, validation_data = val, nb_val_samples = val_number,callbacks = [check_point],max_q_size=2) 
    toc = time.clock()
    print "done training, used %d secs" % (toc-tic)
    
    import matplotlib.pyplot as plt
    plt.switch_backend('agg')
    plt.plot(history.history['loss'])
    plt.plot(history.history['val_loss'])
    plt.title('model loss')
    plt.ylabel('loss')
    plt.xlabel('epoch')
    plt.legend(['train', 'val'], loc='upper left')
    plt.savefig('output/loss.jpg')
    #plt.show()
    plt.close()
