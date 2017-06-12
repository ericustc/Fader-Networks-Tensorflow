import tensorflow as tf
import numpy as np
import optparse
import os
import shutil
import time
import random
import sys
import pickle

from layers import *

from tensorflow.examples.tutorials.mnist import input_data
from scipy.misc import imsave
from PIL import Image
from tqdm import tqdm


class Fader():

	def run_parser(self):

		self.parser = optparse.OptionParser()

		self.parser.add_option('--num_iter', type='int', default=1000, dest='num_iter')
		self.parser.add_option('--batch_size', type='int', default=100, dest='batch_size')
		self.parser.add_option('--img_width', type='int', default=32, dest='img_width')
		self.parser.add_option('--img_height', type='int', default=32, dest='img_height')
		self.parser.add_option('--img_depth', type='int', default=3, dest='img_depth')
		self.parser.add_option('--attr_size', type='int', default=10, dest='attr_size')
		self.parser.add_option('--num_groups', type='int', default=3, dest='num_groups')
		self.parser.add_option('--num_blocks', type='int', default=4, dest='num_blocks')
		self.parser.add_option('--max_epoch', type='int', default=20, dest='max_epoch')
		self.parser.add_option('--n_samples', type='int', default=50000, dest='n_samples')
		self.parser.add_option('--test', action="store_true", default=False, dest="test")
		self.parser.add_option('--steps', type='int', default=10, dest='steps')
		self.parser.add_option('--enc_size', type='int', default=256, dest='enc_size')
		self.parser.add_option('--dec_size', type='int', default=256, dest='dec_size')
		self.parser.add_option('--model', type='string', default="draw_attn", dest='model_type')
		self.parser.add_option('--dataset', type='string', default="cifar-10", dest='dataset')


	def initializer(self):

		self.run_parser()

		opt = self.parser.parse_args()[0]

		self.max_epoch = opt.max_epoch
		self.batch_size = opt.batch_size
		self.dataset = opt.dataset

		if(self.dataset == 'cifar-10'):
			self.img_width = 32
			self.img_height = 32
			self.img_depth = 3
		elif(self.dataset == 'Imagenet'):
			self.img_width = 256
			self.img_height = 256
			self.img_depth = 3
		else :
			self.img_width = opt.img_width
			self.img_height = opt.img_height
			self.img_depth = opt.img_depth

		self.img_size = self.img_width*self.img_height*self.img_depth
		self.attr_size = opt.attr_size
		self.num_groups = opt.num_groups
		self.num_blocks = opt.num_blocks
		self.num_images_per_file = 10000
		self.num_files = 5
		self.num_images = self.num_images_per_file*self.num_files
		self.num_test_images = opt.num_test_images
		self.model = "Fader"
		self.to_test = opt.test
		self.load_checkpoint = False
		self.do_setup = True

		self.tensorboard_dir = "./output/" + self.model + "/" + self.dataset + "/tensorboard"
		self.check_dir = "./output/"+ self.model + "/" + self.dataset +"/checkpoints"
		self.images_dir = "./output/" + self.model + "/" + self.dataset + "/imgs"


	def load_dataset(self, mode='train'):

		self.train_images = np.zeros([self.num_images,self.img_size], dtype=np.float32)
		self.train_labels = np.zeros([self.num_images], dtype=np.int32)

		for i in range(0, 5):
			file_path = os.path.join(os.path.dirname(__file__), "../../datasets/cifar-10-python/cifar-10-batches-py/data_batch_" + str(i+1))
			print(file_path)
			with open(file_path, mode='rb') as file:
				data = pickle.load(file, encoding='bytes')
				temp_images = np.array(data[b'data'])
				temp_labels = np.array(data[b'labels']).astype(np.int32)
				self.train_images[i*self.num_images_per_file:(i+1)*self.num_images_per_file,:] = temp_images
				self.train_labels[i*self.num_images_per_file:(i+1)*self.num_images_per_file] = temp_labels
		
		self.train_images = np.reshape(self.train_images,[self.num_images, self.img_height, self.img_width, self.img_depth])


	def normalize_input(self, imgs):

		return imgs/127.5-1.0

	def encoder(self, input_enc, name="Encoder"):

		with tf.variable_scope(name) as scope:

			o_c1 = general_conv2d(input_enc, 16, name="C16")
			o_c2 = general_conv2d(o_c1, 32, name="C32")
			o_c3 = general_conv2d(o_c2, 64, name="C64")
			o_c4 = general_conv2d(o_c3, 128, name="C128")
			o_c5 = general_conv2d(o_c4, 256, name="C256")
			o_c6 = general_conv2d(o_c5, 512, name="C512_1")
			o_c7 = general_conv2d(o_c6, 512, name="C512_2")

			return o_c7

	def decoder(self, input_dec, name="Decoder"):

		with tf.variable_scope(name) as scope:

			o_d1 = general_deconv2d(input_dec, 512, name="D512_2")
			tf.concat(o_d1, self.input_attr, 3)
			o_d2 = general_deconv2d(o_d1, 256, name="D512_1")
			tf.concat(o_d2, self.input_attr, 3)
			o_d3 = general_deconv2d(o_d2, 128, name="D256")
			tf.concat(o_d3, self.input_attr, 3)
			o_d4 = general_deconv2d(o_d3, 64, name="D128")
			tf.concat(o_d4, self.input_attr, 3)
			o_d5 = general_deconv2d(o_d4, 32, name="D64")
			tf.concat(o_d5, self.input_attr, 3)
			o_d6 = general_deconv2d(o_d5, 16, name="D32")
			tf.concat(o_d6, self.input_attr, 3)
			o_d7 = general_deconv2d(o_d6, 3, name="D16")

			return o_d7


	def cifar_model_setup(self):

		self.input_imgs = tf.placeholder(tf.float32, [self.batch_size, self.img_height, self.img_width, self.img_depth])
		self.input_attr = tf.placeholder(tf.int32, [self.batch_size, 1, 1, self.attr_size])

		o_enc = self.encoder(input_enc)
		o_dec = slef.decoder(o_enc)



	def model_setup(self):

		with tf.variable_scope("Model") as scope:

			self.input_imgs = tf.placeholder(tf.float32, [self.batch_size, self.img_height, self.img_width, self.img_depth])
			self.input_labels = tf.placeholder(tf.int32, [self.batch_size])

			if (self.dataset == 'cifar-10'):
				self.cifar_model_setup()
			else :
				print("No such dataset exist. Exiting the program")
				sys.exit()

		self.model_vars = tf.trainable_variables()
		for var in self.model_vars: print(var.name, var.get_shape())

		self.do_setup = False