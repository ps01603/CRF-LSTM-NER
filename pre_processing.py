import sklearn.preprocessing
# import utils
import collections
import codecs
# import utils_nlp
import re
import time
import token
import os
import pickle
import random
import json
import timeit
import numpy as np

path_train = '../data/CoNLL2003/eng.train'
path_eval = '../data/CoNLL2003/eng.testa'
path_test = '../data/CoNLL2003/eng.testb'

def initial_2idxs(config):


	start = timeit.default_timer()
	print("Building vocab...")
	count_token = {} 
	count_label = {} 
	count_character = {}

	datasets = [('train',config.path_train), ('eval', config.path_eval), ('test', config.path_test)]
	for dataset in datasets:
	    count_token[dataset[0]], count_label[dataset[0]], count_character[dataset[0]] = get_vocabs(dataset[1], separator = config.separator, lowercase = config.lowercase)

	vocab_token_corpus = count_token['train'] + count_token['eval'] + count_token['test']
	vocab_label = count_label['train'] + count_label['eval'] + count_label['test']
	vocab_char = count_character['train'] + count_character['eval'] + count_character['test']

	# sorted the vocabu by frequency 
	vocab_token_corpus = [x[0] for x in vocab_token_corpus.most_common()]
	vocab_label = [x[0] for x in vocab_label.most_common()]
	vocab_char = [x[0] for x in vocab_char.most_common()]

	# future features: limit the vocabulary by threshold
	###############################################
	# if config.vocabulary_threshold > 1:
	#     vocab_token_corpus = 
	###############################################

	# vocab in pre-trained embedding
	# filename_glove = '../data/glove/glove.6B.100d.txt'
	vocab_glove = get_glove_vocab(config.filename_glove)

	# selected only common vocabs in corpus and pre-trained embedding(like glove)
	vocab_token_final = [token for token in vocab_token_corpus if token.strip() in vocab_glove]
	vocab_token_final = ['$UNK$'] + vocab_token_final


	# generate 2idx mapping dict for token, char, label
	# path = '../data/idx/'
	# save_idx = True
	# paths = ['../data/idx/token2idx.json', '../data/idx/label2idx.json', '../data/idx/tag2idx.json']

	token2idx = get_2idx(vocab_token_final, config.save_idx, config.file_token_idx)
	char2idx = get_2idx(vocab_char, config.save_idx, config.file_char_idx)
	label2idx = get_2idx(vocab_label, config.save_idx, config.file_label_idx)

	# get embedding lookup table
	lookup_table = get_embedding_lookup_table(token2idx, config.filename_glove, config.dim_word, config.save_table, config.lookup_table_file_path)

	stop = timeit.default_timer()
	print("vocabulary for this corpus: {} tokens, {} labels, {} chars"
	      .format(len(vocab_token_final), len(vocab_char),len(vocab_label)))
	print('vocabulary construction time: ', stop - start) 

	# update config
	config.set_n_label(len(vocab_label))
	config.set_n_word(len(vocab_token_final))
	config.set_n_char(len(vocab_char))
	config.set_lookup_table(lookup_table)



	return token2idx, char2idx, label2idx, lookup_table

def get_vocabs(filepath, separator = ' ', lowercase = True):
    
    count_token = collections.Counter()
    count_label = collections.Counter()
    count_character = collections.Counter()
    
    if filepath:
        f = codecs.open(filepath, 'r', 'UTF-8')
        for line in f:
            line = line.strip().split(separator)

            #skip sentence separator
            if len(line) == 0 or len(line[0]) == 0 or '-DOCSTART-' in line[0]:
                continue
            
            token = str(line[0])
            for character in token:
                count_character.update({character: 1})
                
            # lowercase & digit
            if lowercase:
                token = str(line[0]).lower()
            else:
                token = str(line[0])
                
            # use the digit in pretrained embedding
#             if token.isdigit():
#                 token = '$NUM$'
                
            label = str(line[-1])
            count_token.update({token: 1})
            count_label.update({label: 1})              
        
        f.close()    
            
    return count_token, count_label, count_character


def get_glove_vocab(filename):
    vocab = set()
    with open(filename) as f:
        for line in f:
            word = line.strip().split(' ')[0]
            vocab.add(word)
    return vocab



def get_embedding_lookup_table(vocab, glove_filename, dim = 100, save_table = False, file_path = None):

    embeddings = np.zeros([len(vocab), dim])
    with open(glove_filename) as f:
        for line in f:
            line = line.strip().split(' ')
            word = line[0]
            embedding = [float(x) for x in line[1:]]
            if word in vocab:
                word_idx = vocab[word]
                embeddings[word_idx] = np.asarray(embedding)
                
    # save lookup table
    if save_table:
        if not os.path.exists(os.path.dirname(file_path)):
            try:
                os.makedirs(os.path.dirname(file_path))
            except OSError as exc: # Guard against race condition
                if exc.errno != errno.EEXIST:
                    raise                    
        with open(file_path, 'w+') as fp:
            np.savez_compressed(trimmed_filename, embeddings=embeddings)
            
    return embeddings



def get_2idx(vocabu, save_idx = False, file_path = None):
    dictionary = dict()
    for idx, word in enumerate(vocabu):
        word = word.strip()
        dictionary[word] = idx
        
    # save index    
    if save_idx:
        if not os.path.exists(os.path.dirname(file_path)):
            try:
                os.makedirs(os.path.dirname(file_path))
            except OSError as exc: # Guard against race condition
                if exc.errno != errno.EEXIST:
                    raise                    
        with open(file_path, 'w+') as fp:
            json.dump(dictionary, fp, indent=4)
            
    return dictionary


def get_inputs(dataset, token2idx, char2idx, label2idx, config):

    dataset_filepath = None
    if dataset == 'train':
        dataset_filepath = config.path_train
    elif dataset == 'eval':
        dataset_filepath = config.path_eval
    elif dataset == 'test':
        dataset_filepath = config.path_test
    else:
        print("unknown dataset: ", dataset)


    separator = config.separator
    lowercase = config.lowercase
    
    # collection per sentence
    # format [[[char_idxs], word_idx], ...]
    sentence_token = []
    # format [[label], ...]
    sentence_label = []
    
    # format [[sentence1_token], [sentence2_token], ...]
    tokens = []
    # format [[sentence1_label], [sentence2_label], ...]
    labels = []

    # go throught whole CoNLL file
    f = codecs.open(dataset_filepath, 'r', 'UTF-8')
    for line in f:
        line = line.strip().split(separator)
        # encouter a new sentence
        if len(line) == 0 or len(line[0]) == 0 or '-DOCSTART-' in line[0]:
            if len(sentence_token) > 0:
                labels.append(sentence_label)
                tokens.append(sentence_token)
                sentence_label = []
                sentence_token = []
            continue
                
        token = str(line[0])
        label = str(line[-1])    
        # 1. preprocess word
        if lowercase:
            word = token.lower()
        # don't use NUM
#         if word.isdigit():
#             word = NUM

        # char idxs
        char_idxs = []
        for char in word:
            if char in char2idx:
                char_idxs += [char2idx[char]]  
            else:
                print("encounter UNK char:", char)
        
        # word idx
        if word in token2idx:
            word_idx = token2idx[word]
        else:
            word_idx = token2idx['$UNK$']
        
        # label idx
        if label in label2idx:
            label_idx = label2idx[label]
        else:
            print("encounter UNK label:", label)
            
        sentence_token.append((char_idxs, word_idx))
        sentence_label.append(label_idx)

    if len(sentence_token) > 0:
        tokens.append(sentence_token)
        labels.append(sentence_label)

    f.close()
    
    return tokens, labels